"""Routers del motor de tareas: tasks, completions, rooms, subjects."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import Room, Subject, Task, TaskCompletion
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.task import (
    CompleteRequest,
    PlaceTaskRequest,
    RoomCreate,
    RoomOut,
    RoomUpdate,
    SubjectCreate,
    SubjectOut,
    SubjectUpdate,
    TaskCreate,
    TaskDoneResponse,
    TaskOut,
    TaskUpdate,
)
from app.services.engine import TaskRules, compute_next_cursor
from app.services.home import task_pending
from app.services.notify import tz_of
from app.services.pending import en_utc

router = APIRouter(prefix="/api", tags=["tasks"])


# ---------------------------------------------------------------- helpers

def _rules(task: Task) -> TaskRules:
    return TaskRules(
        rec_type=task.rec_type,
        rec_interval=task.rec_interval,
        rec_unit=task.rec_unit,
        rec_week_mask=task.rec_week_mask,
        rec_day_of_month=task.rec_day_of_month,
        rec_anchor=task.rec_anchor,
        rec_next_due=task.rec_next_due,
    )


async def _get_owned_task(task_id: int, user: User, db: AsyncSession) -> Task:
    stmt = select(Task).options(selectinload(Task.completions)).where(Task.id == task_id, Task.user_id == user.id)
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    if task.archived_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea archivada")
    return task


def _serialize(task: Task, today: date | None = None) -> dict:
    data = {
        "id": task.id,
        "category": task.category,
        "title": task.title,
        "notes": task.notes,
        "room_id": task.room_id,
        "subject_id": task.subject_id,
        "extracurricular_id": task.extracurricular_id,
        "due_on": task.due_on,
        "due_at": task.due_at,
        "assigned_on": task.assigned_on,
        "created_by": task.created_by,
        "notify": task.notify,
        "rec_type": task.rec_type,
        "rec_interval": task.rec_interval,
        "rec_unit": task.rec_unit,
        "rec_week_mask": task.rec_week_mask,
        "rec_day_of_month": task.rec_day_of_month,
        "rec_anchor": task.rec_anchor,
        "rec_next_due": task.rec_next_due,
        "rotation_group_id": task.rotation_group_id,
        "rotation_index": task.rotation_index,
        "pending_from_class": task.pending_from_class,
        "est_minutes": task.est_minutes,
        # Sale con zona explícita a propósito. Leída de SQLite, la columna la
        # declara con zona pero el valor vuelve sin ella, y un "2026-09-21T13:00:00"
        # sin "Z" lo lee `new Date()` como las 13:00 **del navegador**: una hora
        # distinta según dónde esté el cliente, que es justo lo que se guardó para
        # evitar. Pasarlo por `en_utc` deja claro que ese reloj es UTC.
        "planned_start": en_utc(task.planned_start) if task.planned_start else None,
        "planned_minutes": task.planned_minutes,
        "done_minutes": task.done_minutes,
        "last_done_on": task.last_done_on,
        "archived_at": task.archived_at,
        "sort": task.sort,
        "created_at": task.created_at,
        "done": sorted(c.done_on for c in task.completions),
    }
    if today is not None:
        data["pending"] = task_pending(task, today)
    return data


# ---------------------------------------------------------------- tasks

@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TaskOut:
    task = Task(user_id=user.id, **payload.model_dump())
    if task.rec_type is not None:
        from app.services.engine import next_nominal

        if task.rec_type in ("daily", "weekly_days", "month_day"):
            task.rec_next_due = next_nominal(_rules(task), task.rec_anchor or date.today())
        elif task.rec_next_due is None:
            task.rec_next_due = task.rec_anchor or date.today()
    db.add(task)
    await db.commit()
    await db.refresh(task, ["completions"])
    return TaskOut(**_serialize(task))


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    date: date | None = Query(default=None, description="Día a consultar (por defecto hoy)"),
    category: str | None = Query(default=None, description="Filtrar por categoría"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    day = date or datetime.now(UTC).date()
    stmt = (
        select(Task)
        .options(selectinload(Task.completions))
        .where(Task.user_id == user.id, Task.archived_at.is_(None))
        .order_by(Task.sort, Task.created_at)
    )
    if category:
        stmt = stmt.where(Task.category == category)
    tasks = (await db.execute(stmt)).scalars().all()
    return [TaskOut(**_serialize(t, day)) for t in tasks]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int, payload: TaskUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TaskOut:
    task = await _get_owned_task(task_id, user, db)
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    for k, v in changes.items():
        setattr(task, k, v)
    await db.commit()
    await db.refresh(task)
    return TaskOut(**_serialize(task, datetime.now(UTC).date()))


# ---------------------------------------------------------------- colocacion

@router.post("/tasks/{task_id}/place", response_model=TaskOut)
async def place_task(
    task_id: int, payload: PlaceTaskRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TaskOut:
    """Coloca la tarea en el hueco que empieza en `payload.start`.

    Colocarla no la da por hecha ni le cambia la fecha límite: solo decide **cuándo**
    se hace, que es lo que la línea necesita para pintar el bloque y partir el hueco.
    Si la tarea estaba en otro sitio, se mueve (volver a llamar con otra hora la
    recoloca), porque "mover" y "colocar" son el mismo gesto con distinto final.

Acepta `minutes` en cualquiera de los dos casos:
    - Si viene, es lo que el usuario contestó al colocar y manda sobre cualquier
      estimación previa.
    - Si no viene, se conserva el `planned_minutes` que ya tuviera (mover sin volver
      a preguntar), y si tampoco lo tiene se usa `DEFAULT_PLANNED_MINUTES`.

    La hora se guarda **en UTC** a propósito. SQLite tira el offset al escribir, así
    que lo único que sobrevive es la hora de reloj: si se guardara la hora local tal
    cual, un servidor en Chile leería de vuelta una hora distinta a la que se escribió.
    Convertir a UTC antes y devolver la zona al leer (`pending._en_utc`) es lo que hace
    que dé igual dónde esté el servidor.
    """
    task = await _get_owned_task(task_id, user, db)
    inicio = payload.start
    if inicio.tzinfo is None:
        # Sin zona no se sabe qué quería decir el cliente. Se lee como hora del
        # usuario, que es lo que alguien que teclea "18:00" quiere decir, y no como
        # UTC, que es un detalle de la máquina.
        inicio = inicio.replace(tzinfo=tz_of(user))
    task.planned_start = inicio.astimezone(UTC)
    task.planned_minutes = payload.minutes or task.planned_minutes
    await db.commit()
    await db.refresh(task)
    return TaskOut(**_serialize(task, datetime.now(UTC).date()))


@router.delete("/tasks/{task_id}/place", status_code=status.HTTP_204_NO_CONTENT)
async def unplace_task(
    task_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """Quita la tarea de la línea sin borrarla.

    Solo se limpian las dos columnas de colocación: la tarea sigue pendiente y sigue
    en "qué toca hoy". Guardar el `planned_minutes` tampoco hace falta —si se vuelve a
    colocar más tarde se puede volver a preguntar— y borrarlo sería tirar información
    que el usuario ya dio.
    """
    task = await _get_owned_task(task_id, user, db)
    task.planned_start = None
    task.planned_minutes = None
    await db.commit()


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    task = await _get_owned_task(task_id, user, db)
    await db.delete(task)
    await db.commit()


# ---------------------------------------------------------------- completions

@router.post("/tasks/{task_id}/complete", response_model=TaskDoneResponse)
async def complete_task(
    task_id: int,
    payload: CompleteRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskDoneResponse:
    task = await _get_owned_task(task_id, user, db)
    today = datetime.now(UTC).date()
    done_on = (payload.done_on if payload and payload.done_on else today)

    dup = (
        await db.execute(
            select(TaskCompletion).where(TaskCompletion.task_id == task.id, TaskCompletion.done_on == done_on)
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ocurrencia ya completada")

    db.add(TaskCompletion(task_id=task.id, done_on=done_on))
    task.last_done_on = done_on
    task.done_minutes += payload.minutes if payload and payload.minutes else 0

    if task.rec_type is not None:
        task.rec_next_due = compute_next_cursor(_rules(task), done_on)

    await db.commit()
    return TaskDoneResponse(id=task.id, done_on=done_on, rec_next_due=task.rec_next_due)


@router.delete("/tasks/{task_id}/complete/{done_on}", status_code=status.HTTP_204_NO_CONTENT)
async def undo_completion(
    task_id: int, done_on: date, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    task = await _get_owned_task(task_id, user, db)
    await db.execute(
        delete(TaskCompletion).where(TaskCompletion.task_id == task.id, TaskCompletion.done_on == done_on)
    )
    await db.commit()


# ---------------------------------------------------------------- rooms

@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(
    payload: RoomCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RoomOut:
    room = Room(user_id=user.id, **payload.model_dump())
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return RoomOut(**room.__dict__)


@router.get("/rooms", response_model=list[RoomOut])
async def list_rooms(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[RoomOut]:
    rows = await db.execute(select(Room).where(Room.user_id == user.id).order_by(Room.sort_order, Room.name))
    return [RoomOut(**r.__dict__) for r in rows.scalars().all()]


@router.patch("/rooms/{room_id}", response_model=RoomOut)
async def update_room(
    room_id: int, payload: RoomUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> RoomOut:
    room = (
        await db.execute(select(Room).where(Room.id == room_id, Room.user_id == user.id))
    ).scalar_one_or_none()
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Habitación no encontrada")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(room, k, v)
    await db.commit()
    await db.refresh(room)
    return RoomOut(**room.__dict__)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    room = (
        await db.execute(select(Room).where(Room.id == room_id, Room.user_id == user.id))
    ).scalar_one_or_none()
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Habitación no encontrada")
    await db.delete(room)
    await db.commit()


# ---------------------------------------------------------------- subjects

@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
async def create_subject(
    payload: SubjectCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SubjectOut:
    subject = Subject(user_id=user.id, **payload.model_dump())
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return SubjectOut(**subject.__dict__)


@router.get("/subjects", response_model=list[SubjectOut])
async def list_subjects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[SubjectOut]:
    rows = await db.execute(select(Subject).where(Subject.user_id == user.id).order_by(Subject.name))
    return [SubjectOut(**s.__dict__) for s in rows.scalars().all()]


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
async def update_subject(
    subject_id: int, payload: SubjectUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SubjectOut:
    subject = (
        await db.execute(select(Subject).where(Subject.id == subject_id, Subject.user_id == user.id))
    ).scalar_one_or_none()
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(subject, k, v)
    await db.commit()
    await db.refresh(subject)
    return SubjectOut(**subject.__dict__)


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    subject = (
        await db.execute(select(Subject).where(Subject.id == subject_id, Subject.user_id == user.id))
    ).scalar_one_or_none()
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")
    await db.delete(subject)
    await db.commit()