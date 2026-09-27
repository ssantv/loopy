"""Tests de endpoints del módulo colegio: calendario y sesiones adelantadas.

SQLite en memoria vía override de `get_db` (patrón ASGI, no toca la DB dev).
"""

from datetime import date
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registra todas las tablas
from app.db import Base, get_db
from app.main import app
from app.models.task import Subject


@pytest.fixture
async def env():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield SimpleNamespace(client=c, maker=maker)
    app.dependency_overrides.clear()


async def _register_and_login(env, email="kal@test.com") -> str:
    r = await env.client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "s3cret123",
            "profile_type": "child",
            "birth_date": "2015-01-01",
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


async def _authed(env, email="kal@test.com") -> None:
    tok = await _register_and_login(env, email)
    env.client.headers["Authorization"] = f"Bearer {tok}"


async def _mk_subject(env, **kw) -> int:
    payload = {
        "name": kw.get("name", "Sociales"),
        "color": "#ff0000",
        "days_resumen": kw.get("days_resumen", 1),
        "days_estudio": kw.get("days_estudio", 1),
        "days_practica": kw.get("days_practica", 1),
        "days_repaso": kw.get("days_repaso", 1),
    }
    if "resumen_total_pages" in kw:
        payload["resumen_total_pages"] = kw["resumen_total_pages"]
    r = await env.client.post("/api/subjects", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _mk_exam(env, subject_id: int, exam_date: date) -> int:
    r = await env.client.post("/api/exams", json={"subject_id": subject_id, "exam_date": exam_date.isoformat()})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ---------------------------------------------------------------- calendario

async def test_calendar_vacio(env):
    await _authed(env)
    r = await env.client.get("/api/calendar", params={"from": "2026-09-24", "to": "2026-09-26"})
    assert r.status_code == 200
    assert r.json()["days"] == {}


async def test_calendar_plan_de_examen(env):
    await _authed(env)
    sid = await _mk_subject(env)
    await _mk_exam(env, sid, date(2026, 9, 28))
    r = await env.client.get("/api/calendar", params={"from": "2026-09-24", "to": "2026-09-27"})
    assert r.status_code == 200
    days = r.json()["days"]
    assert list(days) == ["2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"]
    first = days["2026-09-24"]["plan"]
    assert len(first) == 1
    assert first[0]["phase"] == "resumen"  # examen 28/09, cfg 1,1,1,1 -> D-4 resumen
    assert first[0]["subject_name"] == "Sociales"
    assert first[0]["status"] is None
    assert first[0]["session"] is False


async def test_calendar_estado_completado(env):
    await _authed(env)
    sid = await _mk_subject(env)
    eid = await _mk_exam(env, sid, date(2026, 9, 30))

    r = await env.client.post(f"/api/exams/{eid}/plan/2026-09-26", json={"date": "2026-09-26"})
    assert r.status_code in (200, 201), r.text

    r = await env.client.get("/api/calendar", params={"from": "2026-09-26", "to": "2026-09-26"})
    plan = r.json()["days"]["2026-09-26"]["plan"]
    assert plan[0]["status"] == "done"


async def test_calendar_rango_muy_grande(env):
    await _authed(env)
    r = await env.client.get("/api/calendar", params={"from": "2026-09-24", "to": "2028-09-24"})
    assert r.status_code == 400


# ---------------------------------------------------------------- sesiones adelantadas

async def test_add_session_incrementa_pages_de_resumen(env):
    await _authed(env)
    sid = await _mk_subject(env, resumen_total_pages=10)

    r = await env.client.post(f"/api/subjects/{sid}/sessions", json={"date": "2026-09-24", "phase": "resumen"})
    assert r.status_code == 200
    assert r.json()["phase"] == "resumen"

    async with env.maker() as db:
        subj = (await db.execute(select(Subject).where(Subject.id == sid))).scalar_one()
        assert subj.resumen_done_pages == 1


async def test_add_session_estudio_no_toca_pages(env):
    await _authed(env)
    sid = await _mk_subject(env, resumen_total_pages=10)

    r = await env.client.post(f"/api/subjects/{sid}/sessions", json={"date": "2026-09-24", "phase": "estudio"})
    assert r.status_code == 200

    async with env.maker() as db:
        subj = (await db.execute(select(Subject).where(Subject.id == sid))).scalar_one()
        assert subj.resumen_done_pages == 0


async def test_add_session_por_defecto_hoy(env):
    from datetime import UTC, datetime

    await _authed(env)
    sid = await _mk_subject(env)
    r = await env.client.post(f"/api/subjects/{sid}/sessions", json={})
    assert r.status_code == 200
    assert r.json()["date"] == datetime.now(UTC).date().isoformat()


async def test_undo_session(env):
    await _authed(env)
    sid = await _mk_subject(env, resumen_total_pages=10)

    await env.client.post(f"/api/subjects/{sid}/sessions", json={"date": "2026-09-24", "phase": "resumen"})
    r = await env.client.delete(f"/api/subjects/{sid}/sessions/2026-09-24")
    assert r.status_code == 200
    assert r.json()["removed"] is True

    async with env.maker() as db:
        subj = (await db.execute(select(Subject).where(Subject.id == sid))).scalar_one()
        assert subj.resumen_done_pages == 0


async def test_delete_session_no_existente(env):
    await _authed(env)
    sid = await _mk_subject(env)
    r = await env.client.delete(f"/api/subjects/{sid}/sessions/2026-09-24")
    assert r.status_code == 200
    assert r.json()["removed"] is False