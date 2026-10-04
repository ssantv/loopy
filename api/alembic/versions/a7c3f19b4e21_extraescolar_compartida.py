"""extraescolar compartida con el adulto

Añade `extracurriculars.affects_parent` para distinguir las dos situaciones
reales: la extraescolar que solo ocupa el día del niño (música por videollamada,
deberes de tarde) y la que además obliga al adulto a llevarle o pasar de ruta.

El valor por defecto es False a propósito. Es el caso mayoritario y, sobre todo,
es el que no cambia el comportamiento de lo que ya había creado: una extraescolar
que no dice nada es del niño sola. Un servidor con `server_default="0"` en vez de
un default solo de Python para que la columna pueda añadirse NOT NULL sobre una
tabla con filas ya dentro.

Revision ID: a7c3f19b4e21
Revises: 34541e9d1439
Create Date: 2026-10-03 12:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3f19b4e21"
down_revision: Union[str, None] = "34541e9d1439"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "extracurriculars",
        sa.Column("affects_parent", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("extracurriculars", "affects_parent")