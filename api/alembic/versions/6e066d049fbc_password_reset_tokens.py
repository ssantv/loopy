"""password_reset_tokens

Revision ID: 6e066d049fbc
Revises: 787fe4318d13
Create Date: 2026-09-27 20:08:50.189693

Nota: el autogenerate también detectó un NOT NULL en `users.updated_at`. Es deriva
preexistente del esquema (no está relacionada con este cambio) y se deja fuera a
propósito: mezclarla aquí tocaría una tabla ya desplegada sin necesidad.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6e066d049fbc"
down_revision: str | None = "787fe4318d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_password_reset_tokens_token_hash"), "password_reset_tokens", ["token_hash"], unique=True
    )
    op.create_index(op.f("ix_password_reset_tokens_user_id"), "password_reset_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_password_reset_tokens_user_id"), table_name="password_reset_tokens")
    op.drop_index(op.f("ix_password_reset_tokens_token_hash"), table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
