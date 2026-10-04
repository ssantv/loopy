"""Resolución de citas: qué bloquea un día concreto y para quién.

Aquí vive la única lógica que no es un CRUD, y es la que hace fácil equivocarse:
`-fecha` no significa "toda la vida". Una cita puntual solo existe ese día, y una
semanal solo en su día de la semana entre `first_on` y `until`.

El otro detalle importante es que **la cuenta va por horario, no por persona ni por
cita**. Un cumpleaños que afecta a tres personas ocupa una hora del día, no tres: si
se sumara por persona, el día parecería tres veces más lleno de lo que está. Y dos
citas que se pisan ocupan la unión, no la suma, por la misma razón.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentPerson
from app.services.tramos import minutos as minutos_de_tramos


@dataclass(frozen=True)
class Ocurrencia:
    """Una cita en un día concreto, ya resuelta a minutos."""

    cita: Appointment
    minutos: int

    @property
    def compartida(self) -> bool:
        return len(self.cita.afectados) > 0


def ocurre_en(cita: Appointment, day: date) -> bool:
    """¿Esta cita bloquea `day`?

    - Puntual: solo su día, y nunca antes de crearla (el pasado no se rellena solo).
    - Semanal: su día de la semana desde `first_on`, hasta `until` si lo hay.
    """
    if day < cita.first_on:
        return False
    if not cita.repeats_weekly:
        return day == cita.first_on
    if cita.until is not None and day > cita.until:
        return False
    return day.weekday() == cita.first_on.weekday()


async def citas_de(db: AsyncSession, user_id: int, day: date) -> list[Ocurrencia]:
    """Citas que bloquean `day` a `user_id`, de más temprano a más tarde.

    Son las que creó (`owner_id`) más las que le afectan por estar en la tabla
    puente. La consulta elige **una sola** tabla en cada rama, así que una cita
    nunca sale duplicada por estar a la vez en las dos: el día del dueño y el día
    de un niño son días distintos.
    """
    como_afectado = select(AppointmentPerson.cita_id).where(AppointmentPerson.user_id == user_id)
    citas = (
        (
            await db.execute(
                select(Appointment).where(
                    or_(Appointment.owner_id == user_id, Appointment.id.in_(como_afectado))
                )
            )
        )
        .scalars()
        .unique()
        .all()
    )
    lista = [Ocurrencia(cita=c, minutos=c.minutos) for c in citas if ocurre_en(c, day)]
    lista.sort(key=lambda o: (o.cita.start_time, o.cita.title))
    return lista


def minutos_bloqueados(ocurrencias: list[Ocurrencia]) -> int:
    """Minutos que el día está ocupado de verdad, **contando cada solape una vez**.

    Dos cosas que se pisan no ocupan el doble: una cita de 10:00 a 12:00 y otra de
    11:00 a 13:00 dejan el día ocupado de 10:00 a 13:00, que son 180 minutos. Sumar
    daría 240 y le robaría una hora al tiempo de estudio del día, que es justo lo que
    no se puede robar en un día ya apretado.

    Una cita que afecta a tres personas sigue valiendo una hora, no tres: `citas_de`
    devuelve cada cita una sola vez y aquí solo se unen horarios.
    """
    return minutos_de_tramos(o.cita.tramo for o in ocurrencias)