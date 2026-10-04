"""citas de la familia

Citas con dos tablas: `appointments` (el bloque fijo) y `appointment_people` (a
quién afecta además del adulto que la creó).

Tabla puente y no una columna `user_id` porque una cita puede bloquear a varias
personas a la vez: el cumpleaños de un familiar ocupa el día del adulto y el de sus
dos hijos. Los dos CASCADE son los de siempre: si se borra el adulto, sus citas
desaparecen; si se borra un niño, sale de las citas de las que estaba afectado sin
tocar las de los demás.

Revision ID: 34541e9d1439
Revises: 15b791dfdcf7
Create Date: 2026-10-03 12:14:42.821364

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "34541e9d1439"
down_revision: Union[str, None] = "15b791dfdcf7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("place", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("first_on", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("repeats_weekly", sa.Boolean(), nullable=False),
        sa.Column("until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_appointments_first_on"), "appointments", ["first_on"], unique=False)
    op.create_index(op.f("ix_appointments_owner_id"), "appointments", ["owner_id"], unique=False)
    op.create_table(
        "appointment_people",
        sa.Column("cita_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cita_id"], ["appointments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        # Compuesta y no dos FKs sueltas: la misma persona no puede estar dos
        # veces en la misma cita, y eso lo garantiza la clave primaria.
        sa.PrimaryKeyConstraint("cita_id", "user_id"),
    )
    op.create_index(op.f("ix_appointment_people_user_id"), "appointment_people", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_appointment_people_user_id"), table_name="appointment_people")
    op.drop_table("appointment_people")
    op.drop_index(op.f("ix_appointments_owner_id"), table_name="appointments")
    op.drop_index(op.f("ix_appointments_first_on"), table_name="appointments")
    op.drop_table("appointments")