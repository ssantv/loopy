"""Schemas Pydantic para el módulo colegio (niño)."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExamCreate(BaseModel):
    subject_id: int
    exam_date: date
    notes: str | None = None
    # Si este examen necesita mas (o menos) tiempo que su asignatura.
    prep_minutes_override: int | None = Field(default=None, ge=0, le=100000)


class ExamUpdate(BaseModel):
    subject_id: int | None = None
    exam_date: date | None = None
    notes: str | None = None
    prep_minutes_override: int | None = Field(default=None, ge=0, le=100000)


class ExamOut(BaseModel):
    id: int
    subject_id: int
    subject_name: str | None = None
    exam_date: date
    notes: str | None
    prep_minutes_override: int | None = None
    created_at: datetime


class StudyCompletionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    exam_id: int | None
    subject_id: int
    day: date = Field(alias="date")
    phase: str
    status: str  # done | skip


class StudyDoneRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    day: date | None = Field(default=None, alias="date", description="Día del plan; por defecto hoy")
    status: str = Field(default="done", pattern="^(done|skip)$")


class SubjectSessionRequest(BaseModel):
    """Sesión de estudio adelantada (sin examen): fase y fecha en que se hizo."""

    day: date | None = Field(default=None, alias="date", description="Día; por defecto hoy")
    phase: str = Field(default="resumen", pattern="^(resumen|estudio|practica|repaso|repaso-final)$")


class StudyUndoResponse(BaseModel):
    removed: bool


class PlanItemOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    day: date = Field(alias="date")
    phase: str  # repaso-final | repaso | practica | estudio | resumen
    offset: int
    status: str | None = Field(default=None, description="done | skip | None (pendiente)")
    done_at: datetime | None = None
    label: str | None = None  # p.ej. "remata el resumen (llevas X de Y hojas)"
    minutes: int = 30  # duración de la sesión de ese día


class PlanProgressOut(BaseModel):
    """El plan en minutos y sesiones, para poder decirlo sin jerga."""

    session_minutes: int
    prep_minutes: int
    total_sessions: int
    total_minutes: int
    done_sessions: int
    pending_sessions: int
    pending_minutes: int


class ExamPlanOut(BaseModel):
    exam: ExamOut
    subject: dict
    items: list[PlanItemOut]
    resumen_done_pages: int
    resumen_total_pages: int | None
    resumen_omitted: bool
    resumen_partial: bool
    progress: PlanProgressOut


class ExtracurricularCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    start_on: date | None = None
    end_on: date | None = None


class ExtracurricularUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    start_on: date | None = None
    end_on: date | None = None


class ExtracurricularOut(BaseModel):
    id: int
    name: str
    day_of_week: int
    start_time: time
    end_time: time
    start_on: date | None
    end_on: date | None


class WorkSessionCreate(BaseModel):
    kind: str = Field(pattern="^(homework|study|project)$")
    task_id: int | None = None
    planned_seconds: int = Field(default=0, ge=0)
    actual_seconds: int = Field(ge=0)
    completed_at: datetime | None = None


class WorkSessionOut(BaseModel):
    id: int
    kind: str
    task_id: int | None
    planned_seconds: int
    actual_seconds: int
    completed_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------- check-in


class CheckinConfigOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    # Campo `checkin_time` con alias JSON "time": el nombre del atributo no puede
    # coincidir con el tipo `time` porque Pydantic evalúa anotaciones diferidas.
    checkin_time: time = Field(alias="time")
    week_mask: int  # bit 0 = Lunes .. bit 6 = Domingo


class CheckinConfigUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool | None = None
    checkin_time: time | None = Field(default=None, alias="time")
    week_mask: int | None = Field(default=None, ge=0, le=127)


class CheckinToneOut(BaseModel):
    notification_tone: str
    template: str  # texto del push del check-in en el tono del niño


class QuickAddItem(BaseModel):
    """Alta rápida del check-in: deber | examen | proyecto."""

    type: Literal["deber", "examen", "proyecto"]
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subject_id: int | None = None
    exam_date: date | None = None
    est_minutes: int | None = Field(default=None, ge=1)
    pending_from_class: bool = False
    due_on: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_per_type(self) -> "QuickAddItem":
        if self.type in ("deber", "proyecto") and not self.title:
            raise ValueError(f"El tipo '{self.type}' necesita un título")
        if self.type == "examen":
            if self.subject_id is None:
                raise ValueError("El examen necesita una asignatura")
            if self.exam_date is None:
                raise ValueError("El examen necesita fecha")
            if self.title:
                raise ValueError("El examen no lleva título (se usa el de la asignatura)")
        return self


class QuickAddRequest(BaseModel):
    day: date | None = Field(default=None, description="Día de los deberes; por defecto hoy")
    items: list[QuickAddItem] = Field(min_length=1, max_length=30)


class QuickAddDeberOut(BaseModel):
    id: int
    kind: Literal["deber"] = "deber"
    title: str
    subject_id: int | None
    due_on: date | None
    est_minutes: int | None
    pending_from_class: bool


class QuickAddProyectoOut(BaseModel):
    id: int
    kind: Literal["proyecto"] = "proyecto"
    title: str
    subject_id: int | None
    due_on: date | None
    est_minutes: int | None


class QuickAddExamenOut(BaseModel):
    id: int
    kind: Literal["examen"] = "examen"
    subject_id: int
    subject_name: str | None
    exam_date: date
    notes: str | None


class QuickAddResponse(BaseModel):
    day: date
    deberes: list[QuickAddDeberOut]
    proyectos: list[QuickAddProyectoOut]
    examenes: list[QuickAddExamenOut]


# ---------------------------------------------------------------- calendario


class CalendarTaskOut(BaseModel):
    id: int
    title: str
    category: str
    subject_id: int | None
    due_on: date | None
    done: bool  # completada ese día exacto


class CalendarPlanOut(BaseModel):
    exam_id: int | None  # None -> sesión adelantada (sin examen)
    subject_id: int
    subject_name: str | None
    subject_color: str | None
    phase: str  # resumen | estudio | practica | repaso | repaso-final
    date: date
    offset: int
    status: str | None  # done | skip | None (pendiente)
    done_at: datetime | None
    label: str | None
    session: bool = False  # True si es sesión adelantada (no viene del plan)


class CalendarDayOut(BaseModel):
    tasks: list[CalendarTaskOut] = []
    plan: list[CalendarPlanOut] = []


class CalendarOut(BaseModel):
    from_date: date
    to: date
    days: dict[str, CalendarDayOut]