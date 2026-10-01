"""Modelos del módulo colegio (niño): exámenes, completions de estudio, extraescolares y sesiones."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.task import Subject


def _now() -> datetime:
    return datetime.now(UTC)


class Exam(Base):
    """Examen de una asignatura. El plan de estudio se calcula en tiempo de consulta."""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True, nullable=False)
    exam_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Si este examen concreto necesita mas (o menos) tiempo que su asignatura,
    # se pisa aqui el total. NULL = usa el de la asignatura.
    prep_minutes_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    subject: Mapped[Subject] = relationship()


class StudyCompletion(Base):
    """Lo único que se persiste del plan es el 'hecho'. Clave semántica (exam_id, date).

    - `exam_id` NULL → sesión de **resumen adelantado** (sin examen).
    - `status='skip'` → día saltado (enfermo, etc.): desaparece del bloque atrasada
      sin fingir que se estudió.
    """

    __tablename__ = "study_completions"
    __table_args__ = (UniqueConstraint("user_id", "exam_id", "date", name="uq_study_exam_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True, nullable=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # resumen | estudio | practica | repaso | repaso-final
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="done")  # done | skip
    done_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    exam: Mapped[Exam | None] = relationship()


class Extracurricular(Base):
    """Actividad extraescolar: solo contexto (timeline) + entrada del heurístico de carga."""

    __tablename__ = "extracurriculars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 lun .. 6 dom
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    start_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ScheduleSlot(Base):
    """Un día en el que el niño tiene una asignatura: el horario escolar.

    No guarda horas, solo qué días toca cada asignatura, porque eso es lo que
    hace falta para calcular la fecha límite de un deber ("el próximo día que
    tengo esta asignatura"). `day_of_week` usa la convención del resto del
    proyecto: 0 = lunes .. 6 = domingo (igual que `date.weekday()`).
    """

    __tablename__ = "schedule_slots"
    __table_args__ = (UniqueConstraint("user_id", "subject_id", "day_of_week", name="uq_schedule_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True, nullable=False)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0 lun .. 6 dom
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OffDay(Base):
    """Rango de días sin cole: vacaciones, puentes, semana de exams...

    Se guarda como intervalo `start_on..end_on` porque casi siempre son varios
    días seguidos; un día suelto es simplemente `start_on == end_on`. Los rangos
    se pueden solapar: a la hora de consultarlos solo importa la unión.
    """

    __tablename__ = "off_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    start_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # "Vacaciones de Navidad", "Puente del Pilar"...
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HomeworkTemplate(Base):
    """Deber frecuente guardado como atajo ("Ficha de mates", "Leer 20 min").

    Es solo una sugerencia para el alta rápida: al aplicarla, el frontend la
    manda a `/api/checkin/items` como cualquier otro deber, así que la
    plantilla no ata a nada del motor de tareas.
    """

    __tablename__ = "homework_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    est_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CheckinConfig(Base):
    """Configuración del check-in diario del niño (hora + días de la semana).

    `week_mask` usa el mismo bitmask que las tareas: bit 0 = Lunes .. bit 6 = Domingo.
    """

    __tablename__ = "checkin_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Columna 'time' (nombre de planto): el atributo cambia para no chocar con la
    # anotación `Mapped[time]` en el mismo modelo.
    checkin_time: Mapped[time] = mapped_column("time", Time, nullable=False)
    week_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=127)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=lambda: datetime.now(UTC)
    )


class WorkSession(Base):
    """Sesión de trabajo registrada por el temporizador (deberes) o pomodoro (estudio)."""

    __tablename__ = "work_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # homework | study | project | task
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    planned_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)