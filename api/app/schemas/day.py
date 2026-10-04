"""Esquemas del timeline del día."""

from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel

# Los tipos de bloque, con los mismos valores que `app.services.day`.
CITA = "cita"
EXTRAESCOLAR = "extraescolar"
COMPARTIDA = "extraescolar_compartida"
COMIDA = "comida"


class DayBlockOut(BaseModel):
    """Un rato que no se puede usar para otra cosa.

    `affected` dice a quién le afecta además del propio usuario: en una cita, los
    niños; en una extraescolar compartida, el niño que hay que llevar.

    `slot` solo lo traen las comidas (`desayuno`, `cena`…): es lo que distingue un
    café de las diez de un tentempié de las cinco cuando el menú no tiene nada
    planificado y el título se queda en el nombre de la franja.
    """

    kind: str
    title: str
    start: time
    end: time
    minutes: int
    place: str | None = None
    affected: list[str] = []
    cita_id: int | None = None
    extra_id: int | None = None
    slot: str | None = None


class HuecoOut(BaseModel):
    """Un tramo del horario en juego que no cubre ningún bloque."""

    start: time
    end: time
    minutes: int


class DayTimelineOut(BaseModel):
    """Lo que ocupa el día y los huecos que quedan dentro del horario en juego.

    `blocked_minutes` es el mismo número que devuelve `day-load`, no un cálculo
    paralelo: si los dos endpoints dijeran cosas distintas sobre el mismo día,
    alguno de los dos estaría mintiendo y sería imposible saber cuál.

    `free_minutes` **no** es `ventana - blocked_minutes`. Es la suma de `huecos`,
    que tiene en cuenta las comidas, y las comidas no entran en `blocked_minutes`
    porque no se cobran contra el tiempo de estudio. Quien quiera saber cuánto
    puede estudiar, use `blocked_minutes`; quien quiera saber cuándo colocar algo,
    `huecos`.
    """

    date: date
    blocks: list[DayBlockOut]
    blocked_minutes: int
    free_minutes: int
    huecos: list[HuecoOut] = []