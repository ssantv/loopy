"""Carga de un día: cuánto trabajo hay encima y si el plan de estudio cabe.

Este módulo responde a la pregunta que el calendario ya calculaba y **tiraba**:
`unplaced_study_minutes`, los minutos del plan que no encuentran hueco bajo el
tope diario. Aquí se enseña junto al resto de lo que ocupa el día, para que el
número signifique algo en lugar de existir solo en un JSON que nadie lee.

Tres bloques, porque son tres cosas distintas y no deben mezclarse:

- **Estudio**: el plan ya repartido (`plan_spread`), que es lo único que
  `User.study_max_minutes` limita. El reparto se pide para un solo día, pero
  sale de la misma función que usa el calendario: si aquí no cabe y allí sí,
  sería un bug, no una diferencia de criterio.
- **Tareas**: lo pendiente de hoy **más lo atrasado**, que es exactamente lo que
  Mi día enseña. Cada tarea vale lo que el temporizador ha medido de verdad si hay
  historial, y su `est_minutes` si no. Las que no tienen ni una cosa ni la otra
  se cuentan aparte en vez de inventar 25 minutos: un total con relleno es peor
  que admitir que no se sabe.
- **Extraescolares**: tiempo de pared en el que no se puede estudiar. No entra en
  el tope (el tope es de estudio, no del día entero), pero explica por qué un día
  puede no dar para más.
- **Citas**: otro tiempo de pared, y del mismo tipo, pero del que se decide a mano
  (dentista, cumpleaños). Se cuenta aparte para poder decir "tienes una cita" en vez
  de "tienes algo bloqueado".

`blocked_minutes` es la **unión** de ambos, no la suma: si una cita se pisa con una
extraescolar, esa media hora en común está ocupada una vez, no dos. Decirlo de otra
forma declararía el día más lleno de lo que está y le quitaría estudio al usuario.
Por eso `extracurricular_minutes` y `appointment_minutes` son medidas independientes
y su suma puede pasarse de `blocked_minutes`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.school import Extracurricular
from app.models.user import User
from app.services.appointments import citas_de
from app.services.estimates import kind_de_categoria, ritmos_reales
from app.services.pending import pending_items
from app.services.plan_spread import spread_exams
from app.services.schedule import extras_compartidas_de, load_school_calendar
from app.services.tramos import minutos as minutos_de_tramos


@dataclass(frozen=True)
class DayLoad:
    """Lo que ocupa un día, en minutos, y si el plan de estudio cabe en el tope."""

    date: date
    # 0 = sin tope (el usuario no ha puesto ninguno).
    daily_max_minutes: int
    study_minutes: int
    study_done_minutes: int
    task_minutes: int
    tasks_pending: int
    tasks_without_estimate: int
    blocked_minutes: int
    unplaced_study_minutes: int
    exams_pending: int
    # Medidas por clase de bloqueo, para poder nombrarlas en la interfaz. No suman
    # `blocked_minutes`: si una cita se pisa con una extraescolar, la unión los cuenta
    # una vez y estas dos lo cuentan dos.
    extracurricular_minutes: int = 0
    appointment_minutes: int = 0
    appointments_count: int = 0

    @property
    def total_minutes(self) -> int:
        """Todo lo que ocupa el día: estudio + tareas + tiempo de pared."""
        return self.study_minutes + self.task_minutes + self.blocked_minutes

    @property
    def over_cap_minutes(self) -> int:
        """Estudio por encima del tope diario. 0 si no hay tope o si cabe."""
        if self.daily_max_minutes <= 0:
            return 0
        return max(0, self.study_minutes - self.daily_max_minutes)


def _tramos_de_extras(extras: Iterable[Extracurricular]) -> list[tuple[int, int]]:
    """Cada extraescolar como tramo `(inicio, fin)` en minutos desde medianoche."""
    return [
        (e.start_time.hour * 60 + e.start_time.minute, e.end_time.hour * 60 + e.end_time.minute) for e in extras
    ]


async def day_load(db: AsyncSession, user: User, day: date) -> DayLoad:
    """Carga de `day` para `user` (hoy, por defecto, en la interfaz)."""
    spread = await spread_exams(db, user, day, day)

    study = 0
    study_done = 0
    for t in spread.plan_por_dia.get(day, []):
        hecho = spread.completed_by_exam.get(t.exam_id, {}).get(day) if t.exam_id is not None else None
        if hecho is not None:
            study_done += t.minutes
        else:
            study += t.minutes

    overdue, todays = await pending_items(db, user, day)
    tareas = [*overdue, *todays]
    ritmos = await ritmos_reales(db, user, [(kind_de_categoria(t.category), t.id) for t in tareas])
    task_minutes = 0
    sin_estimar = 0
    for t in tareas:
        real = ritmos.get((kind_de_categoria(t.category), t.id))
        if real is not None:
            task_minutes += real
        elif t.est_minutes:
            task_minutes += t.est_minutes
        else:
            sin_estimar += 1

    cal = await load_school_calendar(db, user.id)
    extras = cal.extras_on(day)

    # Las extraescolares de los hijos que además ocupan este día (hay que llevarles).
    # Se unen con las propias en vez de sumarse: si coinciden en hora, para este
    # usuario es un único tramo ocupado, no dos.
    compartidas = await extras_compartidas_de(db, user.id, day)
    tramos_extras = [*_tramos_de_extras(extras), *_tramos_de_extras(compartidas)]
    extras_minutes = minutos_de_tramos(tramos_extras)

    # Las citas del día, una vez cada una. `citas_de` ya viene filtrada por día y
    # ordenada, así que no hace falta volver a agrupar.
    citas = await citas_de(db, user.id, day)
    tramos_citas = [o.cita.tramo for o in citas]
    citas_minutes = minutos_de_tramos(tramos_citas)

    # `blocked_minutes` une **las dos clases juntas**, no las suma. Un niño con
    # extraescolar de 17:00 a 18:00 mientras el adulto tiene una cita de 17:30 a
    # 18:30 tiene 90 minutos ocupados, aunque cada parte por separado diga 60: son
    # las dos cosas a la vez, y contarlas por separado declares media hora de más
    # como si el día estuviera libre.
    return DayLoad(
        date=day,
        daily_max_minutes=user.study_max_minutes,
        study_minutes=study,
        study_done_minutes=study_done,
        task_minutes=task_minutes,
        tasks_pending=len(tareas),
        tasks_without_estimate=sin_estimar,
        blocked_minutes=minutos_de_tramos([*tramos_extras, *tramos_citas]),
        unplaced_study_minutes=sum(t.minutes for t in spread.sin_cabida),
        exams_pending=len(spread.exam_meta),
        extracurricular_minutes=extras_minutes,
        appointment_minutes=citas_minutes,
        appointments_count=len(citas),
    )
