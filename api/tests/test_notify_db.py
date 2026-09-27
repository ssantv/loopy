"""Tests de integración del outbox/poller con SQLite en memoria."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registra todas las tablas
from app.db import Base
from app.models.adult import DailySummaryConfig
from app.models.notify import NotificationOutbox, PushSubscription
from app.models.school import CheckinConfig
from app.models.task import Task
from app.models.user import User
from app.services import notify as N

NOW = datetime(2026, 9, 20, 9, 0)  # domingo 09:00 UTC → Madrid 11:00


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _WebPushExc(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = _Resp(status_code)


async def _session(monkeypatch=None, send_raises=None):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    if monkeypatch is not None:
        async def _fake_send(sub, payload, _raises=send_raises):
            if _raises is not None:
                raise _raises
        monkeypatch.setattr(N, "_send_push", _fake_send)
    return maker


async def _seed_user(maker) -> tuple[int, int]:
    async with maker() as db:
        user = User(email="x@x.com", password_hash="h", profile_type="adult", timezone="Europe/Madrid")
        db.add(user)
        await db.flush()
        db.add(
            PushSubscription(
                user_id=user.id, endpoint="https://push.example/ep1", p256dh="k", auth="a"
            )
        )
        await db.commit()
        return user.id, user.id


# ---------------------------------------------------------------- fill_outbox

@pytest.mark.asyncio
async def test_fill_outbox_crea_y_deduplica():
    maker = await _session()
    user_id, _ = await _seed_user(maker)
    async with maker() as db:
        # tarea puntual hoy con hora futura (12:00 Madrid = 10:00 UTC).
        # El cliente manda `due_at` en hora local (reloj de pared); SQLite lo
        # devuelve naive y el servicio lo interpreta como hora local del usuario.
        db.add(
            Task(
                user_id=user_id,
                category="puntual",
                title="Sacar basura",
                due_on=NOW.date(),
                due_at=datetime(2026, 9, 20, 12, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                notify=True,
                rec_type=None,
            )
        )
        db.add(DailySummaryConfig(user_id=user_id, summary_time=time(8, 0), week_mask=1 << 6))
        db.add(CheckinConfig(user_id=user_id, checkin_time=time(20, 0), week_mask=1))
        await db.commit()

    async with maker() as db:
        added = await N.fill_outbox(db, NOW)
        await db.commit()
    assert added == 3

    async with maker() as db:
        rows = (await db.execute(select(NotificationOutbox))).scalars().all()
        kinds = {r.kind: r for r in rows}
        assert set(kinds) == {"reminder", "checkin", "summary"}
        assert kinds["reminder"].due_at == datetime(2026, 9, 20, 10, 0)  # 12:00 Madrid
        # domingo 8:00 ya pasó (Madrid 11:00) → próximo domingo 27
        assert kinds["summary"].due_at.date().isoformat().endswith("-27")
        # lunes 21 20:00 Madrid = 18:00 UTC
        assert kinds["checkin"].due_at == datetime(2026, 9, 21, 18, 0)

    # segunda pasada: no duplica nada (dedupe por ref + status pending)
    async with maker() as db:
        added2 = await N.fill_outbox(db, NOW)
        await db.commit()
    assert added2 == 0
    async with maker() as db:
        count = len((await db.execute(select(NotificationOutbox))).scalars().all())
    assert count == 3


# ---------------------------------------------------------------- run_poller

@pytest.mark.asyncio
async def test_fill_outbox_sin_suscripciones_no_cola(monkeypatch):
    maker = await _session()
    async with maker() as db:
        user = User(email="y@y.com", password_hash="h", profile_type="adult")
        db.add(user)
        await db.flush()
        db.add(DailySummaryConfig(user_id=user.id, summary_time=time(8, 0), week_mask=1 << 6))
        await db.commit()
    async with maker() as db:
        assert await N.fill_outbox(db, NOW) == 0


@pytest.mark.asyncio
async def test_poller_envia_y_marca_sent(monkeypatch):
    maker = await _session(monkeypatch=monkeypatch)
    user_id, _ = await _seed_user(maker)
    async with maker() as db:
        db.add(
            NotificationOutbox(
                user_id=user_id, kind="test", due_at=NOW, ref="test:1",
                payload={"text": "hola", "url": "/"}, status="pending", attempts=0,
            )
        )
        await db.commit()

    async with maker() as db:
        counts = await N.run_poller(db, NOW)
        await db.commit()
    assert counts == {"sent": 1, "cancelled": 0, "failed": 0, "retry": 0}

    async with maker() as db:
        row = (await db.execute(select(NotificationOutbox))).scalars().one()
        assert row.status == "sent"
        assert row.sent_at == NOW
        # la suscripción sigue viva
        assert len((await db.execute(select(PushSubscription))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_poller_410_borra_suscripcion_y_cancela(monkeypatch):
    maker = await _session(monkeypatch=monkeypatch, send_raises=_WebPushExc(410))
    user_id, _ = await _seed_user(maker)
    async with maker() as db:
        db.add(
            NotificationOutbox(
                user_id=user_id, kind="test", due_at=NOW, ref="test:2",
                payload={"text": "hola", "url": "/"}, status="pending", attempts=0,
            )
        )
        await db.commit()

    async with maker() as db:
        counts = await N.run_poller(db, NOW)
        await db.commit()
    assert counts["cancelled"] == 1

    async with maker() as db:
        assert (await db.execute(select(PushSubscription))).scalars().all() == []
        row = (await db.execute(select(NotificationOutbox))).scalars().one()
        assert row.status == "cancelled"
        assert "410" in (row.last_error or "")


@pytest.mark.asyncio
async def test_poller_429_reintenta_con_backoff(monkeypatch):
    maker = await _session(monkeypatch=monkeypatch, send_raises=_WebPushExc(429))
    user_id, _ = await _seed_user(maker)
    async with maker() as db:
        db.add(
            NotificationOutbox(
                user_id=user_id, kind="test", due_at=NOW, ref="test:3",
                payload={"text": "hola", "url": "/"}, status="pending", attempts=0,
            )
        )
        await db.commit()

    async with maker() as db:
        counts = await N.run_poller(db, NOW)
        await db.commit()
    assert counts == {"sent": 0, "cancelled": 0, "failed": 0, "retry": 1}

    async with maker() as db:
        row = (await db.execute(select(NotificationOutbox))).scalars().one()
        assert row.status == "pending"
        assert row.attempts == 1
        # backoff[0] = 30s
        assert row.next_retry_at == datetime(2026, 9, 20, 9, 0, 30)


@pytest.mark.asyncio
async def test_poller_no_envia_sino_vencido(monkeypatch):
    maker = await _session(monkeypatch=monkeypatch)
    user_id, _ = await _seed_user(maker)
    async with maker() as db:
        db.add(
            NotificationOutbox(
                user_id=user_id, kind="test", due_at=datetime(2026, 9, 20, 10, 0), ref="test:4",
                payload={"text": "futuro", "url": "/"}, status="pending", attempts=0,
            )
        )
        await db.commit()

    async with maker() as db:
        counts = await N.run_poller(db, NOW)
        await db.commit()
    assert counts == {}
    async with maker() as db:
        row = (await db.execute(select(NotificationOutbox))).scalars().one()
        assert row.status == "pending"
        assert row.sent_at is None