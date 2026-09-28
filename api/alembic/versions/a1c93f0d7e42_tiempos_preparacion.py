"""tiempos de preparacion por asignatura y override por examen

Revision ID: a1c93f0d7e42
Revises: 6e066d049fbc
Create Date: 2026-09-28 20:14:31.000000

Por qué: la unidad que se configura pasa a ser MINUTOS ("Matemáticas unas 3
horas"), no días por fase. El número de sesiones sale de dividir, y el
reparto entre fases se hace con los `days_*`, que ahora son pesos relativos.
Un examen concreto puede necesitar más o menos que su asignatura, de ahí
`exams.prep_minutes_override`. `users.course` es el curso del niño.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c93f0d7e42"
down_revision: str | None = "6e066d049fbc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column("prep_minutes", sa.Integer(), nullable=False, server_default="120"),
    )
    op.add_column(
        "subjects",
        sa.Column("session_minutes", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column("exams", sa.Column("prep_minutes_override", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("course", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "course")
    op.drop_column("exams", "prep_minutes_override")
    op.drop_column("subjects", "session_minutes")
    op.drop_column("subjects", "prep_minutes")
