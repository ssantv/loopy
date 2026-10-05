"""Modelos del motor de tareas: rooms, subjects, tasks, completions, rotations."""

from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Room(Base):
    """Habitación (solo categoría hogar de adulto)."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Subject(Base):
    """Asignatura del módulo colegio (niño). Configuración de plan de estudio por asignatura."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # Tiempo de preparacion, en minutos. Es la unidad REAL que configura quien
    # usa la app ("Matematicas unas 3 horas"); el numero de dias del plan se
    # deriva de aqui. `session_minutes` es la duracion de una sesion.
    prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    session_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Reparto del plan entre fases, como PESOS relativos (no dias literales):
    # con 1,1,1,1 cada fase se lleva la cuarta parte de las sesiones.
    # Practica a 0 si la asignatura no la necesita.
    days_resumen: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    days_estudio: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    days_practica: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    days_repaso: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    include_weekends: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Resumen progresivo por hojas (tema sin fecha de examen).
    resumen_total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resumen_done_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Task(Base):
    """Tarea con recurrencias de dos familias:

    - Calendario (`daily` | `weekly_days` | `month_day`): el día nominal siempre
      aparece; marcar por adelantado NO consume la ocurrencia del día real.
    - Día real (`interval` | `rotation_ref`): el siguiente = fecha real de
      completado + intervalo. Marcar por adelantado SÍ consume.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    category: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True
    )  # general | hogar | rutina | colegio-deberes | colegio-trabajo | puntual
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    # De dónde viene el deber cuando lo manda una extraescolar y no una asignatura.
    extracurricular_id: Mapped[int | None] = mapped_column(
        ForeignKey("extracurriculars.id", ondelete="SET NULL"), nullable=True
    )

    # Un día concreto (puntual o "para hoy") o fecha objetivo.
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Día en que se ENCARGA. Distinto de `due_on` (fecha límite): un deber de
    # sociales repartido los lunes y martes, encargado un martes, no es para
    # mañana sino para el siguiente lunes que haya clase. `due_on` se queda
    # fijo en esa fecha aunque el plazo pase, y el deber sigue pendiente.
    assigned_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # --- Cuándo se hace ---
    #
    # `planned_start` es el hueco que el usuario le ha asignado a esta tarea, y a
    # partir de ahí ocupa la línea del día como cualquier otra cosa. Es distinto de
    # `assigned_on` (el día en que se encarga) y de `due_on` (la fecha límite): una
    # tarea puede estar cargada para hoy y decidirse que se hace el jueves.
    #
    # No se reutiliza `est_minutes` para la duración porque ese campo alimenta el
    # reparto de estudio del niño: la duración de lo colocado la contesta el usuario
    # al colocarlo, no es una estimación.
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    planned_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Quién la creó. Lo rellena el adulto cuando le asigna un encargo al niño,
    # para poder listar y cancelar lo que le ha mandado.
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Recurrencia ---
    rec_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True
    )  # daily | weekly_days | month_day | interval | rotation_ref
    rec_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rec_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)  # day | week | month
    rec_week_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)  # bit 0=Lun..6=Dom
    rec_day_of_month: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 0 = último día del mes
    rec_anchor: Mapped[date | None] = mapped_column(Date, nullable=True)
    rec_next_due: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # Rotación: ítems del mismo grupo se turnan (materializado como interval+ancla desfasada).
    rotation_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("rotation_groups.id", ondelete="SET NULL"), nullable=True
    )
    rotation_index: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # --- Colegio (niño) ---
    pending_from_class: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    est_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    done_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_done_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    room: Mapped[Room | None] = relationship()
    subject: Mapped[Subject | None] = relationship()
    completions: Mapped[list["TaskCompletion"]] = relationship(back_populates="task", cascade="all, delete-orphan")

    def is_recurrent(self) -> bool:
        return self.rec_type is not None


class TaskCompletion(Base):
    """Historial: una fila por (tarea, día completado). Solo el 'hecho', nunca el plan."""

    __tablename__ = "task_completions"
    __table_args__ = (UniqueConstraint("task_id", "done_on", name="uq_task_done"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False)
    done_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    task: Mapped[Task] = relationship(back_populates="completions")


class RotationGroup(Base):
    """Grupo de rotación: ítems que se turnan (ej. 1 mes cada uno), materializado
    como tareas `interval` con `rec_anchor` desfasado un periodo entre ítems."""

    __tablename__ = "rotation_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    rec_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rec_unit: Mapped[str] = mapped_column(String(8), nullable=False, default="month")  # day | week | month
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)