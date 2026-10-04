"""Citas: bloques fijos de tiempo que no se pueden mover.

La diferencia con una tarea es la que obliga a tener su propia tabla. Una tarea se
puede posponer a mañana y ocupa el tiempo que haga falta; una cita no: el dentista
es a las 17:00 y llega tarde. `Task.due_at` no sirve porque es **hora de aviso**,
no un rato ocupado — un recordatorio de "saca la basura a las 20:00" no bloquea la
tarde de nadie.

Lo que las hace distintas al resto del modelo es que **afectan a más de una
persona**. El cumpleaños de un familiar ocupa el día del adulto y el de sus dos
niños a la vez; el dentista de uno lo ocupa a él y al adulto que le acompaña. Por
eso la cita no tiene un `user_id`: tiene un `owner_id` (el adulto que la crea y que
siempre está afectado) y una tabla puente con el resto de afectados.

Que varias personas la sufran no significa que el día esté ocupado varias veces: un
cumpleaños de 3 personas sigue siendo una hora de día perdido, no tres. Por eso el
cálculo de carga cuenta citas, no personas.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now().astimezone()


class Appointment(Base):
    """Cita de la familia: un bloque fijo, puntual o semanal.

    `first_on` sigue la convención `_on` del resto del proyecto (`due_on`,
    `start_on`). En una cita puntual **es** la única ocurrencia; si `repeats_weekly`,
    es la primera, y `until` la última.
    """

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # El adulto que la crea. No es "dueño en el sentido de privacidad": todos los
    # niños de su cuenta deben poder verla, y de hecho quedan afectados por ella.
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    place: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    repeats_weekly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Solo tiene sentido si `repeats_weekly`. `None` = sin fin.
    until: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    afectados: Mapped[list[AppointmentPerson]] = relationship(
        back_populates="cita", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def minutos(self) -> int:
        """Duración en minutos.

        Un `end_time` anterior al `start_time` es dato corrupto, no "ocupa la
        noche", así que vale 0 en vez de un número negativo.
        """
        inicio, fin = self.tramo
        return max(0, fin - inicio)

    @property
    def tramo(self) -> tuple[int, int]:
        """`(inicio, fin)` en minutos desde medianoche, para uniones de horario."""
        return (
            self.start_time.hour * 60 + self.start_time.minute,
            self.end_time.hour * 60 + self.end_time.minute,
        )


class AppointmentPerson(Base):
    """A quién afecta una cita además de su adulto.

    El adulto que la crea **siempre** está afectado y por eso no necesita fila aquí:
    si estuviera, se podría quitar a sí mismo y dejar la cita sin dueño visible.
    Solo van los niños.
    """

    __tablename__ = "appointment_people"

    cita_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    cita: Mapped[Appointment] = relationship(back_populates="afectados")


__all__ = ["Appointment", "AppointmentPerson"]