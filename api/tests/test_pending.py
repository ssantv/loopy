"""Tests del listado global de pendientes y marcado masivo (Roadmap paso 7)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registra todas las tablas
from app.db import Base
from app.models.task import Task, TaskCompletion
from app.models.user import User
from app.services.pending import bulk_complete, pending_items

TODAY = date(2026, 9, 20)

FIRST = datetime(2026, 9, 1, tzinfo=UTC)  # ancla de tareas del 1 de septiembre


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(db, user_id: int, **kw) -> int:
    t = Task(user_id=user_id, category=kw.pop("category", "general"), title=kw.pop("title", "x"), **kw)
    db.add(t)
    await db.flush()
    return t.id


async def _user(db, profile="adult") -> int:
    u = User(email=f"{profile}_{datetime.now().timestamp()}@x.com", password_hash="h", profile_type=profile)
    db.add(u)
    await db.flush()
    return u.id


async def _pend_ids(db, user_id: int) -> tuple[list[int], list[int]]:
    user = await _all_user(db, user_id)
    overdue, todays = await pending_items(db, user, TODAY)
    return [t.id for t in overdue], [t.id for t in todays]


async def _all_user(db, user_id: int) -> User:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def test_puntual_atrasada_y_hoy():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        overdue_id = await _seed(db, uid, title="polvo", category="hogar", due_on=date(2026, 9, 18))
        today_id = await _seed(db, uid, title="compra", category="hogar", due_on=TODAY)
        future_id = await _seed(db, uid, title="futuro", category="general", due_on=date(2026, 9, 21))
        await db.commit()
        overdue, todays = await _pend_ids(db, uid)
    assert overdue_id in overdue and future_id not in overdue
    assert today_id in todays and future_id not in todays


async def test_puntual_hecha_no_sale():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        tid = await _seed(db, uid, due_on=date(2026, 9, 18))
        db.add(TaskCompletion(task_id=tid, done_on=date(2026, 9, 18)))
        await db.commit()
        overdue, todays = await _pend_ids(db, uid)
    assert tid not in overdue and tid not in todays


async def test_recurrente_calendario_hoy_y_atrasada():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        daily = await _seed(
            db, uid, title="daily", rec_type="daily", rec_anchor=FIRST.date(), rec_week_mask=0
        )
        weekly = await _seed(
            db, uid, title="semanal", rec_type="weekly_days", rec_week_mask=1, rec_anchor=FIRST.date()
        )  # lunes (2026-09-20 es domingo; lunes previo = 14)
        await db.commit()
        overdue, todays = await _pend_ids(db, uid)
    assert daily in todays
    assert weekly in overdue


async def test_intervalo_atrasado_colapsado_y_no_vencido_fuera():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        vencido = await _seed(
            db, uid, title="riego", rec_type="interval", rec_interval=3, rec_unit="day",
            rec_next_due=date(2026, 9, 12),
        )
        futuro = await _seed(
            db, uid, title="futuro", rec_type="interval", rec_interval=3, rec_unit="day",
            rec_next_due=date(2026, 9, 23),
        )
        await db.commit()
        overdue, todays = await _pend_ids(db, uid)
    assert vencido in overdue
    assert futuro not in overdue and futuro not in todays


async def test_archivada_no_sale():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        tid = await _seed(db, uid, due_on=TODAY, archived_at=datetime.now(UTC))
        await db.commit()
        overdue, todays = await _pend_ids(db, uid)
    assert tid not in overdue and tid not in todays


async def test_bulk_complete_marca_todo_y_recalcula_cursor():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        puntual = await _seed(db, uid, title="polvo", due_on=date(2026, 9, 18))
        interval = await _seed(
            db, uid, title="riego", rec_type="interval", rec_interval=3, rec_unit="day",
            rec_next_due=date(2026, 9, 12),
        )
        calendar = await _seed(
            db, uid, title="daily", rec_type="daily", rec_anchor=TODAY, rec_week_mask=0
        )
        await db.commit()

        completed, errors = await bulk_complete(db, (await _all_user(db, uid)), [puntual, interval, calendar], TODAY)

        assert sorted(completed) == sorted([puntual, interval, calendar])
        assert errors == []
        riego = (await db.execute(select(Task).where(Task.id == interval))).scalar_one()
        daily = (await db.execute(select(Task).where(Task.id == calendar))).scalar_one()
        pend = await _pend_ids(db, uid)
        assert riego.rec_next_due == date(2026, 9, 23)  # intervalo: se recalcula desde HOY (hoy + 3)
        assert daily.rec_next_due == date(2026, 9, 21)
        assert pend == ([], [])


async def test_bulk_calendario_atrasada_se_consume_con_su_fecha():
    # Ejemplo clave del planteamiento: "polvo" toca el lunes, falla el lunes →
    # pendiente el resto de la semana; marcarla el domingo consume el lunes y el
    # siguiente vuelve a ser el lunes que viene (sin perder ni adelantar).
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        polvo = await _seed(
            db, uid, title="polvo", rec_type="weekly_days", rec_week_mask=1,
            rec_anchor=date(2026, 9, 14),  # lunes colapsado (atrasada)
        )
        await db.commit()
        overdue, _ = await _pend_ids(db, uid)
        assert overdue == [polvo]

        completed, errors = await bulk_complete(db, (await _all_user(db, uid)), [polvo], TODAY)

        assert completed == [polvo]
        assert errors == []
        t = (await db.execute(select(Task).where(Task.id == polvo))).scalar_one()
        assert t.rec_next_due == date(2026, 9, 21)  # lunes siguiente
        assert await _pend_ids(db, uid) == ([], [])


async def test_bulk_complete_dedupe_y_aunque_una_falle():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        base = await _seed(db, uid, due_on=TODAY)
        forastero_id = await _seed(db, 999999, due_on=TODAY)  # no pertenece al usuario
        await db.commit()
        completed, errors = await bulk_complete(db, (await _all_user(db, uid)), [base, forastero_id], TODAY)

    assert completed == [base]
    details = {e["task_id"]: e["detail"] for e in errors}
    assert forastero_id in details and "no encontrada" in details[forastero_id]


async def test_bulk_complete_y_enviar_dos_veces_sin_pendiente():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        base = await _seed(db, uid, due_on=TODAY)
        await db.commit()
        await bulk_complete(db, (await _all_user(db, uid)), [base], TODAY)
        completed, errors = await bulk_complete(db, (await _all_user(db, uid)), [base], TODAY)
    assert completed == []
    assert errors == [{"task_id": base, "detail": "Sin ocurrencia pendiente"}]


async def test_bulk_complete_archivada_error():
    maker = await _session()
    async with maker() as db:
        uid = await _user(db)
        tid = await _seed(db, uid, due_on=TODAY, archived_at=datetime.now(UTC))
        await db.commit()
        completed, errors = await bulk_complete(db, (await _all_user(db, uid)), [tid], TODAY)
    assert completed == []
    assert errors == [{"task_id": tid, "detail": "Tarea archivada"}]