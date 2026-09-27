"""Schemas Pydantic para el motor de tareas."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    category: str = Field(pattern="^(general|hogar|colegio-deberes|colegio-trabajo|puntual)$")
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = None

    room_id: int | None = None
    subject_id: int | None = None

    due_on: date | None = None
    due_at: datetime | None = None
    notify: bool = False

    rec_type: str | None = Field(default=None, pattern="^(daily|weekly_days|month_day|interval|rotation_ref)$")
    rec_interval: int = Field(default=1, ge=1)
    rec_unit: str | None = Field(default=None, pattern="^(day|week|month)$")
    rec_week_mask: int = Field(default=0, ge=0, le=127)
    rec_day_of_month: int | None = Field(default=None, ge=0, le=31)
    rec_anchor: date | None = None
    rec_next_due: date | None = None

    rotation_group_id: int | None = None
    rotation_index: int | None = None

    pending_from_class: bool = False
    est_minutes: int | None = Field(default=None, ge=1)
    sort: int = 0


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    due_on: date | None = None
    due_at: datetime | None = None
    notify: bool | None = None
    est_minutes: int | None = Field(default=None, ge=1)
    sort: int | None = None
    archived_at: datetime | None = None


class TaskOut(BaseModel):
    id: int
    category: str
    title: str
    notes: str | None
    room_id: int | None
    subject_id: int | None
    due_on: date | None
    due_at: datetime | None
    notify: bool
    rec_type: str | None
    rec_interval: int
    rec_unit: str | None
    rec_week_mask: int
    rec_day_of_month: int | None
    rec_anchor: date | None
    rec_next_due: date | None
    rotation_group_id: int | None
    rotation_index: int | None
    pending_from_class: bool
    est_minutes: int | None
    done_minutes: int
    last_done_on: date | None
    archived_at: datetime | None
    sort: int
    created_at: datetime
    pending: date | None = Field(default=None, description="Ocurrencia pendiente calculada (si toca)")
    done: list[date] = Field(default_factory=list, description="Fechas done_on de las completions")


class TaskDoneResponse(BaseModel):
    id: int
    done_on: date
    rec_next_due: date | None


class CompleteRequest(BaseModel):
    done_on: date | None = Field(default=None, description="Ocurrencia que se completa; por defecto hoy")
    minutes: int | None = Field(default=None, ge=1)


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    sort_order: int = 0
    color: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")


class RoomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = None
    color: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")


class RoomOut(BaseModel):
    id: int
    name: str
    sort_order: int
    color: str | None


class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")
    days_resumen: int = Field(default=1, ge=0)
    days_estudio: int = Field(default=1, ge=0)
    days_practica: int = Field(default=1, ge=0)
    days_repaso: int = Field(default=1, ge=0)
    include_weekends: bool = True
    resumen_total_pages: int | None = Field(default=None, ge=1)


class SubjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern="^#[0-9a-fA-F]{6}$")
    days_resumen: int | None = Field(default=None, ge=0)
    days_estudio: int | None = Field(default=None, ge=0)
    days_practica: int | None = Field(default=None, ge=0)
    days_repaso: int | None = Field(default=None, ge=0)
    include_weekends: bool | None = None
    resumen_total_pages: int | None = Field(default=None, ge=1)


class SubjectOut(BaseModel):
    id: int
    name: str
    color: str | None
    days_resumen: int
    days_estudio: int
    days_practica: int
    days_repaso: int
    include_weekends: bool
    resumen_total_pages: int | None
    resumen_done_pages: int