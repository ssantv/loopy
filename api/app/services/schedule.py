"""Contexto escolar del niño: horario, días sin cole y extraescolares.

Vive aparte de los routers porque lo consultan tres sitios que deben contar
igual: el cálculo de la fecha límite de un deber, el calendario y (más
adelante) el reparto de "organiza tu tarde".

Conceptos:

- **Horario** (`ScheduleSlot`): qué días tiene cada asignatura. No guarda
  horas: solo hace falta para saber "cuándo vuelve a aparecer esta asignatura".
- **Días sin cole** (`OffDay`): rangos de vacaciones/puentes. Sin ellos, la
  fecha límite caería en un puente o en Navidad.
- **Extraescolar** (`Extracurricular`): día de la semana + horas + rango de
  fechas. Ocupa un hueco concreto de la tarde y también sirve como origen de
  deberes (con su propio día para la fecha límite).

Convención de días de la semana en todo el módulo: **0 = lunes .. 6 = domingo**,
que es justo lo que devuelve `date.weekday()`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Extracurricular, OffDay, ScheduleSlot, User

# Tope de búsqueda al Walkar días hacia atrás/adelante. Con el tope de carga
# una ventana de 2 años es más que de sobra y evita bucles infinitos si un
# horario quedara mal configurado.
MAX_LOOKAHEAD_DAYS = 730


def extra_activa_on(extra: Extracurricular, day: date) -> bool:
    """¿La extraescolar existe ya en `day`? Solo mira el rango de fechas.

    El día de la semana lo comprueba quien llama, porque aquí solo interesa la
    pregunta "empezó y no ha terminado".
    """
    if extra.start_on and day < extra.start_on:
        return False
    if extra.end_on and day > extra.end_on:
        return False
    return True


@dataclass(frozen=True)
class SchoolCalendar:
    """Todo lo que hace falta para razonar sobre "qué día es cole" de un niño.

    Se construye una vez por request con `load_school_calendar` y se pasa a las
    funciones puras de aquí, que son las testeables.
    """

    # subject_id -> set de días de la semana (0=lun..6=dom)
    subject_days: dict[int, set[int]] = field(default_factory=dict)
    # Rangos sin cole
    off_ranges: tuple[tuple[date, date], ...] = ()
    # Extraescolares, para "qué hay hoy" y para la fecha límite de sus deberes
    extracurriculars: tuple[Extracurricular, ...] = ()

    # ------------------------------------------------------------ días sin cole

    def is_off_day(self, day: date) -> bool:
        """¿Ese día no hay cole (vacaciones, puente...)? Los rangos se solapan sin problema."""
        return any(start <= day <= end for start, end in self.off_ranges)

    def is_school_day(self, day: date) -> bool:
        return not self.is_off_day(day)

    def next_school_day(self, after: date, *, inclusive: bool = False) -> date:
        """Primer día con cole a partir de `after` (o el propio `after` si `inclusive`).

        Si no se encuentra ningún día con cole dentro del horizonte de búsqueda
        (no debería pasar con un horario normal), devuelve el propio `after`
        para no dejar al llamador sin fecha.
        """
        d = after if inclusive else after + timedelta(days=1)
        for _ in range(MAX_LOOKAHEAD_DAYS):
            if self.is_school_day(d):
                return d
            d += timedelta(days=1)
        return after

    # ------------------------------------------------- próximo día de una asignatura

    def next_class_day(self, subject_id: int | None, after: date, *, fallback_to_school_day: bool = True) -> date:
        """Fecha límite de un deber: el próximo día que hay clase de `subject_id`.

        Regla de negocio (ejemplo del planteamiento): los sociales son lunes y
        martes; si los mandan un martes, no son para mañana, son para el lunes
        siguiente. Se busca el próximo día con clase **estrictamente después**
        de `after` que además no sea día sin cole.

        Si la asignatura no está en el horario (o no tiene ningún día futuro), se
        cae al primer día con cole si `fallback_to_school_day` (por defecto,
        mañana). Devolver "mañana" es mejor que devolver una fecha inventada.
        """
        days = self.subject_days.get(subject_id or -1)
        if days:
            d = after + timedelta(days=1)
            for _ in range(MAX_LOOKAHEAD_DAYS):
                if d.weekday() in days and self.is_school_day(d):
                    return d
                d += timedelta(days=1)
        if fallback_to_school_day:
            return self.next_school_day(after)
        return after

    def extracurricular_day(self, extra_id: int | None, after: date, *, fallback: date | None = None) -> date:
        """Fecha límite de un deber cuya origen es una extraescolar.

        Busca el próximo día de la semana de esa extraescolar que además no sea
        día sin cole y esté dentro de su rango de fechas (`start_on..end_on`).
        """
        extra = self.extracurricular(extra_id)
        if extra is None:
            return fallback if fallback is not None else after
        d = after + timedelta(days=1)
        for _ in range(MAX_LOOKAHEAD_DAYS):
            if d.weekday() == extra.day_of_week and self._extra_active_on(extra, d) and self.is_school_day(d):
                return d
            d += timedelta(days=1)
        return fallback if fallback is not None else after

    def extracurricular(self, extra_id: int | None) -> Extracurricular | None:
        if extra_id is None:
            return None
        return next((e for e in self.extracurriculars if e.id == extra_id), None)

    @staticmethod
    def _extra_active_on(extra: Extracurricular, day: date) -> bool:
        return extra_activa_on(extra, day)

    # ------------------------------------------------------------ extraescolares de hoy

    def extras_on(self, day: date) -> list[Extracurricular]:
        """Extraescolares que caen en ese día concreto (día de semana + rango de fechas)."""
        return [e for e in self.extracurriculars if e.day_of_week == day.weekday() and self._extra_active_on(e, day)]


async def load_school_calendar(db: AsyncSession, user_id: int) -> SchoolCalendar:
    """Carga horario, días sin cole y extraescolares de un usuario."""
    slots = (
        await db.execute(select(ScheduleSlot).where(ScheduleSlot.user_id == user_id))
    ).scalars().all()
    subject_days: dict[int, set[int]] = {}
    for s in slots:
        subject_days.setdefault(s.subject_id, set()).add(s.day_of_week)

    off = (await db.execute(select(OffDay).where(OffDay.user_id == user_id))).scalars().all()
    extras = (
        await db.execute(
            select(Extracurricular)
            .where(Extracurricular.user_id == user_id)
            .order_by(Extracurricular.day_of_week, Extracurricular.start_time)
        )
    ).scalars().all()

    return SchoolCalendar(
        subject_days=subject_days,
        off_ranges=tuple((o.start_on, o.end_on) for o in off),
        extracurriculars=tuple(extras),
    )


async def extras_compartidas_de(db: AsyncSession, parent_id: int, day: date) -> list[Extracurricular]:
    """Extraescolares de los hijos de `parent_id` que además le ocupan a él ese día.

    Solo las marcadas con `affects_parent`. Sin ese filtro entrarían todas, y el
    día del adulto se llenaría con lo que hacen los niños solos: la música por
    videollamada no le quita ni un minuto a quien está en casa.

    Para un niño esto devuelve siempre vacío (busca usuarios cuyo `parent_id` sea
    el suyo, y un niño no es padre de nadie), así que el mismo camino sirve para
    los dos perfiles sin comprobar `profile_type`.
    """
    hijos = (await db.execute(select(User.id).where(User.parent_id == parent_id))).scalars().all()
    if not hijos:
        return []
    extras = (
        await db.execute(
            select(Extracurricular)
            .where(
                Extracurricular.user_id.in_(hijos),
                Extracurricular.affects_parent.is_(True),
                Extracurricular.day_of_week == day.weekday(),
            )
            .order_by(Extracurricular.start_time)
        )
    ).scalars().all()
    return [e for e in extras if extra_activa_on(e, day)]


def school_calendar(
    *,
    subject_days: dict[int, Iterable[int]] | None = None,
    off_ranges: Iterable[tuple[date, date]] = (),
    extracurriculars: Sequence[Extracurricular] = (),
) -> SchoolCalendar:
    """Construye un `SchoolCalendar` a mano, para tests sin BD."""
    return SchoolCalendar(
        subject_days={k: set(v) for k, v in (subject_days or {}).items()},
        off_ranges=tuple(off_ranges),
        extracurriculars=tuple(extracurriculars),
    )
