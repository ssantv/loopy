"""fase2 contexto escolar: horario, días sin cole, plantillas y tareas

Revision ID: 15b791dfdcf7
Revises: be50acb67645
Create Date: 2026-09-29 10:27:22.154320

Notas de SQLite (por qué no sale todo de `alembic revision --autogenerate`):

- `op.create_foreign_key` no existe en SQLite. Añadir la FK dentro del propio
  `add_column` tampoco vale: el dialecto de Alembic lo convierte en un
  `add_constraint` y revienta con `NotImplementedError`. La forma que sí funciona
  es `batch_alter_table` (copia la tabla, la reconstruye y la mueve), que es la
  que ya usaba la migración de la Fase 1.
- Se ignoran a propósito los warnings de "constraint name is None" que genera
  el autogenerate para `tasks`: en esta base las FKs se crearon sin nombre, así
  que no se pueden borrar por nombre. Aquí sí se les pone nombre a las nuevas.
- Se ignora la deriva de `users.updated_at` (NOT NULL en la BD, nullable en el
  modelo) que ya existía antes de esta fase: no es de este cambio y arreglarla
  obligaría a reconstruir `users` con todos sus índices.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "15b791dfdcf7"
down_revision: Union[str, None] = "be50acb67645"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- horario escolar: qué día tiene cada asignatura ---
    op.create_table(
        "schedule_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Evita meter dos veces la misma asignatura el mismo día (importante:
        # el cálculo de la fecha límite cuenta días, no franjas).
        sa.UniqueConstraint("user_id", "subject_id", "day_of_week", name="uq_schedule_slot"),
    )
    op.create_index(op.f("ix_schedule_slots_user_id"), "schedule_slots", ["user_id"], unique=False)
    op.create_index(op.f("ix_schedule_slots_subject_id"), "schedule_slots", ["subject_id"], unique=False)

    # --- días sin cole: rangos de vacaciones/puentes ---
    op.create_table(
        "off_days",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_off_days_user_id"), "off_days", ["user_id"], unique=False)
    # Índice por los dos extremos: las consultas del calendario preguntan
    # "¿hay algún rango que cubra este día?" (start <= d <= end).
    op.create_index(op.f("ix_off_days_start_on"), "off_days", ["start_on"], unique=False)
    op.create_index(op.f("ix_off_days_end_on"), "off_days", ["end_on"], unique=False)

    # --- plantillas de deber ---
    op.create_table(
        "homework_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("est_minutes", sa.Integer(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_homework_templates_user_id"), "homework_templates", ["user_id"], unique=False)

    # --- tareas: día de encargo, origen extraescolar y quién la creó ---
    # Batch mode porque SQLite no admite `ALTER ... ADD CONSTRAINT`.
    with op.batch_alter_table("tasks", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("assigned_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("extracurricular_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_tasks_assigned_on"), ["assigned_on"], unique=False)
        # "Quien la creó" apunta a un adulto que puede borrarse; "de dónde vino
        # el deber" a una extraescolar que puede desaparecer. Por eso SET NULL y
        # no CASCADE: perder el rastro del origen no debe borrar el deber.
        batch_op.create_foreign_key(
            "fk_tasks_created_by", "users", ["created_by"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_tasks_extracurricular_id", "extracurriculars", ["extracurricular_id"], ["id"], ondelete="SET NULL"
        )

    # --- tope de minutos de estudio al día ---
    op.add_column(
        "users",
        sa.Column("study_max_minutes", sa.Integer(), server_default="60", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "study_max_minutes")

    with op.batch_alter_table("tasks", recreate="auto") as batch_op:
        batch_op.drop_constraint("fk_tasks_created_by", type_="foreignkey")
        batch_op.drop_constraint("fk_tasks_extracurricular_id", type_="foreignkey")
        batch_op.drop_index(op.f("ix_tasks_assigned_on"))
        batch_op.drop_column("created_by")
        batch_op.drop_column("extracurricular_id")
        batch_op.drop_column("assigned_on")

    op.drop_index(op.f("ix_homework_templates_user_id"), table_name="homework_templates")
    op.drop_table("homework_templates")
    op.drop_index(op.f("ix_off_days_end_on"), table_name="off_days")
    op.drop_index(op.f("ix_off_days_start_on"), table_name="off_days")
    op.drop_index(op.f("ix_off_days_user_id"), table_name="off_days")
    op.drop_table("off_days")
    op.drop_index(op.f("ix_schedule_slots_subject_id"), table_name="schedule_slots")
    op.drop_index(op.f("ix_schedule_slots_user_id"), table_name="schedule_slots")
    op.drop_table("schedule_slots")
