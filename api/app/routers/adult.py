"""Routers del módulo adulto: hogar por habitaciones, compra y resumen diario.

Planteamiento §2.5 / §5:
- `GET /api/home` agrupa por habitaciones lo pendiente y lo adelantable.
- `POST /api/tasks/{id}/advance` consume la siguiente ocurrencia (next > hoy).
- Compra: lista + comprar/deshacer + quitar (solo lo no comprado) + Recomendar.
- Resumen diario: config (hora + días) y excepciones `skip`/`add`.
Compra y resumen son solo para el perfil adulto.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import DailySummaryConfig, Room, ShoppingItem, SummaryException, Task, TaskCompletion
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.tasks import _get_owned_task, _rules
from app.schemas.adult import (
    HomeGroup,
    HomeItem,
    HomeOut,
    HomeRoom,
    ShoppingItemCreate,
    ShoppingItemOut,
    ShoppingItemUpdate,
    ShoppingRecommendOut,
    SummaryConfigOut,
    SummaryConfigUpdate,
    SummaryExceptionOut,
    SummaryExceptionPut,
    SummaryMonthOut,
)
from app.schemas.task import CompleteRequest, TaskDoneResponse
from app.services.clock import hoy
from app.services.engine import compute_next_cursor
from app.services.home import group_home, next_occurrence
from app.services.shopping import normalize_name, suggest

router = APIRouter(prefix="/api", tags=["adult"])

DEFAULT_SUMMARY_TIME = "20:00"
DEFAULT_SUMMARY_WEEK_MASK = 127


def _require_adult(user: User) -> None:
    if user.profile_type != "adult":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta sección es solo para el perfil adulto",
        )


def _home_item(item: dict) -> HomeItem:
    return HomeItem(**item)


# ---------------------------------------------------------------- hogar

@router.get("/home", response_model=HomeOut)
async def home_day(
    day: date | None = Query(default=None, description="Día a consultar (por defecto hoy local)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HomeOut:
    today = day or hoy(user)
    rooms = (
        (await db.execute(select(Room).where(Room.user_id == user.id).order_by(Room.sort_order, Room.name)))
        .scalars()
        .all()
    )
    tasks = (
        await db.execute(
            select(Task)
            .options(selectinload(Task.completions))
            .where(Task.user_id == user.id, Task.archived_at.is_(None))
            .order_by(Task.sort, Task.created_at)
        )
    ).scalars().all()

    grouped = group_home(tasks, rooms, today)
    rooms_out = [
        HomeRoom(
            id=r["id"],
            name=r["name"],
            color=r["color"],
            pending=[_home_item(i) for i in r["pending"]],
            ahead=[_home_item(i) for i in r["ahead"]],
        )
        for r in grouped["rooms"]
    ]
    no_room = HomeGroup(
        pending=[_home_item(i) for i in grouped["no_room"]["pending"]],
        ahead=[_home_item(i) for i in grouped["no_room"]["ahead"]],
    )
    return HomeOut(day=today, rooms=rooms_out, no_room=no_room)


@router.post("/tasks/{task_id}/advance", response_model=TaskDoneResponse)
async def advance_task(
    task_id: int,
    payload: CompleteRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskDoneResponse:
    """Completa la siguiente ocurrencia (estrictamente después de hoy).

    Regla de las "Adelantadas" (§2.5): marcar aquí **consume** la ocurrencia y
    el siguiente queda tras hoy. Cero cambios si no hay nada que adelantar.
    """
    task = await _get_owned_task(task_id, user, db)
    today = hoy(user)
    target = next_occurrence(task, today)
    if target is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No hay ocurrencia futura que adelantar")

    dup = (
        await db.execute(
            select(TaskCompletion).where(TaskCompletion.task_id == task.id, TaskCompletion.done_on == target)
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ocurrencia ya completada")

    db.add(TaskCompletion(task_id=task.id, done_on=target))
    task.last_done_on = target
    task.done_minutes += payload.minutes if payload and payload.minutes else 0
    if task.rec_type is not None:
        task.rec_next_due = compute_next_cursor(_rules(task), target)
    await db.commit()
    return TaskDoneResponse(id=task.id, done_on=target, rec_next_due=task.rec_next_due)


# ---------------------------------------------------------------- compra

async def _own_item(item_id: int, user: User, db: AsyncSession) -> ShoppingItem:
    row = (
        await db.execute(select(ShoppingItem).where(ShoppingItem.id == item_id, ShoppingItem.user_id == user.id))
    ).scalar_one_or_none()
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ítem no encontrado")
    return row


@router.get("/shopping", response_model=list[ShoppingItemOut])
async def list_shopping(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ShoppingItemOut]:
    _require_adult(user)
    rows = (
        await db.execute(
            select(ShoppingItem)
            .where(ShoppingItem.user_id == user.id, ShoppingItem.deleted_at.is_(None))
            .order_by(ShoppingItem.purchased, ShoppingItem.added_at)
        )
    ).scalars().all()
    return [ShoppingItemOut(**r.__dict__) for r in rows]


@router.post("/shopping", response_model=ShoppingItemOut, status_code=status.HTTP_201_CREATED)
async def create_shopping(
    payload: ShoppingItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShoppingItemOut:
    _require_adult(user)
    item = ShoppingItem(user_id=user.id, name=payload.name, qty=payload.qty or None, source="manual")
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ShoppingItemOut(**item.__dict__)


@router.patch("/shopping/{item_id}", response_model=ShoppingItemOut)
async def update_shopping(
    item_id: int,
    payload: ShoppingItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShoppingItemOut:
    _require_adult(user)
    item = await _own_item(item_id, user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return ShoppingItemOut(**item.__dict__)


@router.post("/shopping/{item_id}/purchase", response_model=ShoppingItemOut)
async def purchase_item(
    item_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ShoppingItemOut:
    _require_adult(user)
    item = await _own_item(item_id, user, db)
    item.purchased = True
    item.purchased_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(item)
    return ShoppingItemOut(**item.__dict__)


@router.post("/shopping/{item_id}/unpurchase", response_model=ShoppingItemOut)
async def unpurchase_item(
    item_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ShoppingItemOut:
    _require_adult(user)
    item = await _own_item(item_id, user, db)
    item.purchased = False
    item.purchased_at = None
    await db.commit()
    await db.refresh(item)
    return ShoppingItemOut(**item.__dict__)


@router.delete("/shopping/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shopping(
    item_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    """"Quitar": solo borra lo que nunca se compró; lo comprado queda como historial."""
    _require_adult(user)
    item = await _own_item(item_id, user, db)
    if item.purchased:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Ya comprado: deshaz la compra antes de quitar"
        )
    await db.delete(item)
    await db.commit()


@router.get("/shopping/recommend", response_model=list[ShoppingRecommendOut])
async def recommend_shopping(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ShoppingRecommendOut]:
    _require_adult(user)
    today = hoy(user)
    since = today - timedelta(days=90)
    # Normalizar en SQL: traemos nombres cronológicos y agrupamos en Python (listas cortas).
    purchased = (
        await db.execute(
            select(ShoppingItem.name, ShoppingItem.qty, ShoppingItem.purchased_at)
            .where(
                ShoppingItem.user_id == user.id,
                ShoppingItem.purchased.is_(True),
                ShoppingItem.deleted_at.is_(None),
                ShoppingItem.purchased_at.is_not(None),
                ShoppingItem.purchased_at
                >= datetime.combine(since, datetime.min.time(), tzinfo=UTC),
            )
            .order_by(ShoppingItem.purchased_at)
        )
    ).all()
    pending = (
        await db.execute(
            select(ShoppingItem.name)
            .where(
                ShoppingItem.user_id == user.id,
                ShoppingItem.purchased.is_(False),
                ShoppingItem.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    suggestions = suggest(
        [(n, q, p.date() if p else today) for n, q, p in purchased],
        today,
        exclude=(normalize_name(n) for n in pending),
    )
    return [ShoppingRecommendOut(name=s["name"], qty=s["qty"], count=s["count"]) for s in suggestions]


# ---------------------------------------------------------------- resumen diario

async def _get_summary_config(user: User, db: AsyncSession) -> DailySummaryConfig:
    conf = (
        await db.execute(select(DailySummaryConfig).where(DailySummaryConfig.user_id == user.id))
    ).scalar_one_or_none()
    if conf is None:
        conf = DailySummaryConfig(
            user_id=user.id,
            summary_time=datetime.strptime(DEFAULT_SUMMARY_TIME, "%H:%M").time(),
            week_mask=DEFAULT_SUMMARY_WEEK_MASK,
        )
        db.add(conf)
        await db.flush()
    return conf


def _summary_out(conf: DailySummaryConfig) -> SummaryConfigOut:
    return SummaryConfigOut(enabled=conf.enabled, summary_time=conf.summary_time, week_mask=conf.week_mask)


@router.get("/summary/config", response_model=SummaryConfigOut)
async def get_summary_config(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SummaryConfigOut:
    _require_adult(user)
    return _summary_out(await _get_summary_config(user, db))


@router.patch("/summary/config", response_model=SummaryConfigOut)
async def patch_summary_config(
    payload: SummaryConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SummaryConfigOut:
    _require_adult(user)
    conf = await _get_summary_config(user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(conf, key, value)
    await db.flush()
    return _summary_out(conf)


@router.get("/summary", response_model=SummaryMonthOut)
async def summary_month(
    month: str = Query(description="Mes en formato YYYY-MM"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SummaryMonthOut:
    _require_adult(user)
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Mes inválido"
        ) from None
    next_first = first.replace(day=1)
    if next_first.month == 1:
        next_first = next_first.replace(year=next_first.year + 1, month=1)
    else:
        next_first = next_first.replace(month=next_first.month + 1)
    rows = (
        await db.execute(
            select(SummaryException)
            .where(
                SummaryException.user_id == user.id,
                SummaryException.date >= first,
                SummaryException.date < next_first,
            )
            .order_by(SummaryException.date)
        )
    ).scalars().all()
    return SummaryMonthOut(
        month=month,
        days=[SummaryExceptionOut(date=r.date, action=r.action) for r in rows],
    )


@router.put("/summary/exceptions/{day}", response_model=SummaryExceptionOut)
async def put_summary_exception(
    day: date,
    payload: SummaryExceptionPut,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SummaryExceptionOut:
    _require_adult(user)
    exc = (
        await db.execute(
            select(SummaryException).where(SummaryException.user_id == user.id, SummaryException.date == day)
        )
    ).scalar_one_or_none()
    if exc is None:
        exc = SummaryException(user_id=user.id, date=day, action=payload.action)
        db.add(exc)
    else:
        exc.action = payload.action
    await db.commit()
    return SummaryExceptionOut(date=day, action=exc.action)


@router.delete("/summary/exceptions/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_summary_exception(
    day: date, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    _require_adult(user)
    await db.execute(
        SummaryException.__table__.delete().where(
            SummaryException.user_id == user.id, SummaryException.date == day
        )
    )
    await db.commit()
