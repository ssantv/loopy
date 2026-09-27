"""Listado global de pendientes y marcado masivo (Roadmap paso 7).

Sobre el motor de tareas, el listado "Pendientes" (ambos perfiles) muestra toda
tarea con ocurrencia pendiente <= hoy (atrasadas + de hoy). El marcado masivo
respeta el contrato del motor (Planteamiento §6):

- **Calendario y puntuales**: la marca consume la ocurrencia que se muestra, con
  `done_on` = esa fecha exacta → "la marca previa NO consume las futuras".
  Consumir una atrasada colapsada deja que la siguiente nominal aparezca normal.
- **Intervalo/rotación**: `done_on` = hoy → "se recalcula desde hoy".
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task, TaskCompletion
from app.models.user import User
from app.services.engine import REAL_FAMILY, as_rules, compute_next_cursor
from app.services.home import task_pending


async def pending_items(db: AsyncSession, user: User, today: date) -> tuple[list[Task], list[Task]]:
    """Tareas con ocurrencia pendiente, separadas en `(atrasadas, de hoy)`.

    Las atrasadas primero; dentro de cada grupo se respeta `sort, created_at`.
    Incluye tareas puntuales (`due_on <= hoy` sin completar) y recurrentes de
    ambas familias. Excluye archivadas.
    """
    rows = await db.execute(
        select(Task)
        .options(selectinload(Task.completions))
        .where(Task.user_id == user.id, Task.archived_at.is_(None))
        .order_by(Task.sort, Task.created_at)
    )
    overdue: list[Task] = []
    todays: list[Task] = []
    for task in rows.scalars().all():
        pend = task_pending(task, today)
        if pend is None:
            continue
        (overdue if pend < today else todays).append(task)
    return overdue, todays


async def bulk_complete(
    db: AsyncSession, user: User, task_ids: list[int], today: date
) -> tuple[list[int], list[dict]]:
    """Completa varias tareas masivamente (por defecto el día de hoy, tz del usuario).

    Por cada tarea: verifica propiedad + no archivada + pendiente, elige el
    `done_on` según la familia (ver docstring del módulo) y aplica el mismo
    efecto que el `complete` unitario. Los fallos se reportan por tarea y no
    abortan el lote.

    Devuelve `(completed_ids, errors)` con `errors = [{"task_id", "detail"}]`.
    """
    completed: list[int] = []
    errors: list[dict] = []
    for task_id in task_ids:
        task = (
            await db.execute(
                select(Task)
                .options(selectinload(Task.completions))
                .where(Task.id == task_id, Task.user_id == user.id)
            )
        ).scalar_one_or_none()
        if task is None:
            errors.append({"task_id": task_id, "detail": "Tarea no encontrada"})
            continue
        if task.archived_at is not None:
            errors.append({"task_id": task_id, "detail": "Tarea archivada"})
            continue
        pend = task_pending(task, today)
        if pend is None:
            errors.append({"task_id": task_id, "detail": "Sin ocurrencia pendiente"})
            continue
        done_on = today if task.rec_type in REAL_FAMILY else pend
        dup = (
            await db.execute(
                select(TaskCompletion).where(
                    TaskCompletion.task_id == task.id, TaskCompletion.done_on == done_on
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            errors.append({"task_id": task_id, "detail": "Ocurrencia ya completada"})
            continue

        db.add(TaskCompletion(task_id=task.id, done_on=done_on))
        task.last_done_on = done_on
        if task.rec_type is not None:
            task.rec_next_due = compute_next_cursor(as_rules(task), done_on)
        completed.append(task.id)

    await db.commit()
    return completed, errors