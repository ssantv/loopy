"""Schemas Pydantic del módulo adulto: hogar, compra y resumen diario."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- hogar

class HomeItem(BaseModel):
    id: int
    category: str
    title: str
    notes: str | None
    room_id: int | None
    due_on: date | None
    due_at: datetime | None
    notify: bool
    rec_type: str | None
    est_minutes: int | None
    last_done_on: date | None
    sort: int
    created_at: datetime
    pending: date | None = None
    next_on: date | None = None
    done: list[date] = Field(default_factory=list)


class HomeGroup(BaseModel):
    pending: list[HomeItem] = Field(default_factory=list)
    ahead: list[HomeItem] = Field(default_factory=list)


class HomeRoom(BaseModel):
    id: int
    name: str
    color: str | None
    pending: list[HomeItem] = Field(default_factory=list)
    ahead: list[HomeItem] = Field(default_factory=list)


class HomeOut(BaseModel):
    day: date
    rooms: list[HomeRoom]
    no_room: HomeGroup


# ---------------------------------------------------------------- compra

class ShoppingItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    qty: str | None = Field(default=None, max_length=80)


class ShoppingItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    qty: str | None = Field(default=None, max_length=80)


class ShoppingItemOut(BaseModel):
    id: int
    name: str
    qty: str | None
    added_at: datetime
    purchased: bool
    purchased_at: datetime | None
    source: str
    source_ref: str | None


class ShoppingRecommendOut(BaseModel):
    name: str
    qty: str | None
    count: int


# ---------------------------------------------------------------- resumen

class SummaryConfigOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    # Campo `summary_time` con alias JSON "time": mismo truco que el check-in
    # (el nombre de atributo no puede coincidir con el tipo `time`).
    summary_time: time = Field(alias="time")
    week_mask: int


class SummaryConfigUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool | None = None
    summary_time: time | None = Field(default=None, alias="time")
    week_mask: int | None = Field(default=None, ge=0, le=127)


class SummaryExceptionOut(BaseModel):
    date: date
    action: Literal["skip", "add"]


class SummaryExceptionPut(BaseModel):
    action: Literal["skip", "add"]


class SummaryMonthOut(BaseModel):
    month: str
    days: list[SummaryExceptionOut]