"""tarea colocada en un hueco

Añade `tasks.planned_start` y `tasks.planned_minutes` para que una tarea pueda
tener hora el día que se hace. Sin esto la línea del día sabe qué ocupa el rato
(citas, extraescolares, comidas) pero no puede decir en qué hueco encaja una tarea,
que es justo lo que faltaba para cerrar el pendiente 11.

`planned_start` es un `DateTime` y no un `Date` a propósito: colocar una tarea a
las 17:25 es una decisión distinta de decidir que el día de la tarea es el 17, y
guardar solo la fecha obligaría a inventar una hora por defecto que no significa
nada para el usuario.

Las dos columnas son nullables y sin valor por defecto porque una tarea sin
colocar es el caso normal: las que ya existen deben seguir siendo válidas y
seguir apareciendo en "qué toca hoy" exactamente igual.

El índice es necesario porque la línea del día busca por fecha: sin él, cada
petición tiene que recorrer la tabla entera de tareas para encontrar las del día.

Revision ID: c4e8b2a91f70
Revises: a7c3f19b4e21
Create Date: 2026-10-04 09:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8b2a91f70"
down_revision: Union[str, None] = "a7c3f19b4e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("planned_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("planned_minutes", sa.Integer(), nullable=True))
    op.create_index(
        "ix_tasks_planned_start",
        "tasks",
        ["planned_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_planned_start", table_name="tasks")
    op.drop_column("tasks", "planned_minutes")
    op.drop_column("tasks", "planned_start")