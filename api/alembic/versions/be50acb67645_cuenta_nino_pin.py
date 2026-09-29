"""cuenta de niño creada por un adulto, con entrada por PIN

Revision ID: be50acb67645
Revises: a1c93f0d7e42
Create Date: 2026-09-29 10:00:34.695916

Por qué: un menor de 11 años no tiene email propio, así que la cuenta de niño
la crea la cuenta adulta que lo gestiona (nuevo `users.parent_id`) y el niño
entra con nombre + PIN en vez de email + contraseña (`users.pin_hash`).
Consecuencia: `users.email` pasa a NULL-able, porque las cuentas de niño ya no
lo tienen; la recuperación de contraseña sigue siendo solo de adultos.
`password_hash` sigue siendo NOT NULL: al crear la cuenta de niño se guarda un
hash aleatorio inservible (nunca se entra por contraseña con ella).

El autogenerate también detectó un NOT NULL en `users.updated_at`. Es deriva
preexistente del esquema (se añadió la columna sin server_default) y, como en
`6e066d049fbc`, se deja fuera a propósito.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "be50acb67645"
down_revision: str | None = "a1c93f0d7e42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite no soporta ALTER de columnas/constraints: todo va en un único
    # batch_alter_table (refleja la tabla original, aplica y la recrea una vez).
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("email", existing_type=sa.VARCHAR(length=320), nullable=True)
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pin_hash", sa.Text(), nullable=True))
        batch_op.create_index(op.f("ix_users_parent_id"), ["parent_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_users_parent_id", "users", ["parent_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    # En SQLite el drop de una FK exige recrear la tabla: batch_alter_table.
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_parent_id", type_="foreignkey")
        # Si quedan niños sin email, el restore a NOT NULL no puede aplicarse.
        batch_op.alter_column("email", existing_type=sa.VARCHAR(length=320), nullable=False)
    op.drop_index(op.f("ix_users_parent_id"), table_name="users")
    op.drop_column("users", "pin_hash")
    op.drop_column("users", "parent_id")
