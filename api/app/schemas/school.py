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
    # Si hay que llevar al niño, la actividad también bloquea el día del adulto.
    # False por defecto: lo mayoritario es que el adulto no la sufra.
    affects_parent: bool = False


class ExtracurricularUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    start_on: date | None = None
    end_on: date | None = None
    affects_parent: bool | None = None


class ExtracurricularOut(BaseModel):
    id: int
    name: str
    day_of_week: int
    start_time: time
    end_time: time
    start_on: date | None
    end_on: date | None
    affects_parent: bool


# ------------------------------------------------------- horario y días sin cole


class TimetableSlotCreate(BaseModel):
    """Una asignatura en un día de la semana. Sin horas: solo importa el día.

    `day_of_week`: 0 = lunes .. 6 = domingo.
    """

    subject_id: int
    day_of_week: int = Field(ge=0, le=6)


class TimetableSlotOut(BaseModel):
    id: int
    subject_id: int
    subject_name: str | None = None
    subject_color: str | None = None
    day_of_week: int


class TimetableOut(BaseModel):
    """Horario agrupado por día, listo para pintar en el frontend."""

    days: dict[int, list[TimetableSlotOut]] = Field(default_factory=dict)


class OffDayCreate(BaseModel):
    """Rango de días sin cole. Un día suelto es `start_on == end_on`."""

    start_on: date
    end_on: date | None = None
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _validate_range(self) -> "OffDayCreate":
        end = self.end_on or self.start_on
        if end < self.start_on:
            raise ValueError("'end_on' no puede ser anterior a 'start_on'")
        self.end_on = end
        return self


class OffDayOut(BaseModel):
    id: int
    start_on: date
    end_on: date
    label: str | None
    days_count: int = Field(description="Cuántos días abarca el rango, ambos incluidos")


# ------------------------------------------------------------ plantillas de deber


class HomeworkTemplateCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    subject_id: int | None = None
    est_minutes: int | None = Field(default=None, ge=1, le=100000)
    sort: int = 0


class HomeworkTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    subject_id: int | None = None
    est_minutes: int | None = Field(default=None, ge=1, le=100000)
    sort: int | None = None


class HomeworkTemplateOut(BaseModel):
    id: int
    title: str
    subject_id: int | None
    subject_name: str | None = None
    est_minutes: int | None
    sort: int
    created_at: datetime


class WorkSessionCreate(BaseModel):
    kind: str = Field(pattern="^(homework|study|project|task)$")
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


class WorkSessionEstimateOut(BaseModel):
    """Corrección de una estimación a partir del historial real del temporizador."""

    suggested_minutes: int | None
    samples: int
    based_on: str
    planned_minutes: int
    actual_minutes: int


# ---------------------------------------------------------------- carga del día


class DayLoadOut(BaseModel):
    """Minutos que ocupa un día y si el plan de estudio cabe en el tope."""

    date: date
    daily_max_minutes: int
    study_minutes: int
    study_done_minutes: int
    task_minutes: int
    tasks_pending: int
    tasks_without_estimate: int
    blocked_minutes: int
    total_minutes: int
    over_cap_minutes: int
    unplaced_study_minutes: int
    exams_pending: int
    # Desglose de `blocked_minutes`: qué parte son extraescolares, qué parte citas y
    # qué parte tareas que el usuario ya colocó en un hueco.
    extracurricular_minutes: int = 0
    appointment_minutes: int = 0
    appointments_count: int = 0
    placed_minutes: int = 0


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
    # Si el deber viene de una extraescolar, su fecha límite es el próximo día
    # de esa extraescolar, no el próximo día de clase de la asignatura.
    extracurricular_id: int | None = None
    # Aplica una plantilla guardada: rellena título/asignatura/minutos de una vez.
    template_id: int | None = None
    # Anula el `day` del request para este item (permite encargar "para el lunes"
    # varios deberes distintos el mismo día).
    assigned_on: date | None = None

    @model_validator(mode="after")
    def _validate_per_type(self) -> "QuickAddItem":
        if self.type in ("deber", "proyecto") and not self.title and not self.template_id:
            raise ValueError(f"El tipo '{self.type}' necesita un título o una plantilla")
        if self.type == "examen":
            if self.subject_id is None:
                raise ValueError("El examen necesita una asignatura")
            if self.exam_date is None:
                raise ValueError("El examen necesita fecha")
            if self.title:
                raise ValueError("El examen no lleva título (se usa el de la asignatura)")
        if self.type == "examen" and (self.template_id or self.extracurricular_id):
            raise ValueError("El examen no admite plantilla ni extraescolar")
        return self


class QuickAddRequest(BaseModel):
    day: date | None = Field(default=None, description="Día en que se encarga; por defecto hoy")
    items: list[QuickAddItem] = Field(min_length=1, max_length=30)


class QuickAddDeberOut(BaseModel):
    id: int
    kind: Literal["deber"] = "deber"
    title: str
    subject_id: int | None
    due_on: date | None
    est_minutes: int | None
    pending_from_class: bool
    # Día en que se encargó, y de dónde vino el deber (asignatura u extraescolar).
    assigned_on: date | None = None
    source_kind: str | None = None  # asignatura | extraescolar | None (sin origen)
    source_name: str | None = None
    due_from_rule: str | None = None  # "próximo día de clase" | "próxima extraescolar" | "manual"


class QuickAddProyectoOut(BaseModel):
    id: int
    kind: Literal["proyecto"] = "proyecto"
    title: str
    subject_id: int | None
    due_on: date | None
    est_minutes: int | None
    assigned_on: date | None = None
    source_kind: str | None = None
    source_name: str | None = None
    due_from_rule: str | None = None


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
    minutes: int = 30  # duración de la sesión de ese día
    session: bool = False  # True si es sesión adelantada (no viene del plan)


class CalendarExtraOut(BaseModel):
    """Extraescolar que cae ese día, ya resuelto a horas concretas."""

    id: int
    name: str
    start_time: time
    end_time: time


class CalendarDayOut(BaseModel):
    tasks: list[CalendarTaskOut] = []
    plan: list[CalendarPlanOut] = []
    # True si el día está marcado como sin cole (vacaciones, puente...).
    no_school: bool = False
    # Etiqueta del rango sin cole que cubre este día, si lo hay ("Navidad").
    off_label: str | None = None
    # Extraescolares de ese día concreto.
    extras: list[CalendarExtraOut] = []


class CalendarOut(BaseModel):
    from_date: date
    to: date
    days: dict[str, CalendarDayOut]
    # Minutos de estudio que no han cabido dentro del tope diario en este rango.
    # El frontend puede avisar ("para esta semana no caben tantos exámenes").
    unplaced_study_minutes: int = 0
    # El tope con el que se repartió, para que el frontend pueda decir
    # "caben 60 al día" en vez de tener que repetir el número en cada sitio.
    daily_max_minutes: int = 60