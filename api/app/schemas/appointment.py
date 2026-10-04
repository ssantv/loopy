"""Esquemas de citas.

`affected_user_ids` son los niños de la cuenta a los que además les afecta. El
adulto que la crea no se lista: siempre está afectado y no se puede quitar.

El tipo `date` se importa como `Fecha` a propósito. Un campo llamado `date` dentro
de la clase **tapa** el nombre del tipo para todo lo que se evalúe después en el
cuerpo de la clase, así que `until: date | None` acabaría intentando hacer
`None | None`. Es un fallo silencioso hasta que Pydantic evalúa las anotaciones.
"""

from __future__ import annotations

from datetime import date as Fecha
from datetime import time

from pydantic import BaseModel, Field, model_validator


class AppointmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    place: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    date: Fecha
    start_time: time
    end_time: time
    repeats_weekly: bool = False
    until: Fecha | None = None
    # Solo ids de niños de la cuenta del adulto. El backend lo comprueba: no vale
    # con que el número exista, tiene que ser hijo suyo.
    affected_user_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _comprobaciones(self) -> AppointmentCreate:
        if self.end_time <= self.start_time:
            raise ValueError("La cita tiene que terminar después de empezar")
        if self.until is not None:
            if not self.repeats_weekly:
                raise ValueError("'until' solo tiene sentido si la cita se repite")
            if self.until < self.date:
                raise ValueError("La cita no puede repetirse hasta un día anterior al primero")
        return self


class AppointmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    place: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    date: Fecha | None = None
    start_time: time | None = None
    end_time: time | None = None
    repeats_weekly: bool | None = None
    until: Fecha | None = None
    affected_user_ids: list[int] | None = None


class AppointmentPersonOut(BaseModel):
    id: int
    display_name: str


class AppointmentOut(BaseModel):
    id: int
    owner_id: int
    title: str
    place: str | None
    notes: str | None
    date: Fecha
    start_time: time
    end_time: time
    repeats_weekly: bool
    until: Fecha | None
    minutes: int
    affected: list[AppointmentPersonOut]