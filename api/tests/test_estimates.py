"""Tests de la corrección de estimaciones a partir de `work_sessions`.

SQLite en memoria vía override de `get_db` (patrón ASGI, no toca la DB dev).
El foco está en las reglas del serviço: mínimo de muestras, preferencia por la
tarea, mediana y umbral de discrepancia. El endpoint es el cable.
"""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registra todas las tablas
from app.db import Base, get_db
from app.main import app
from app.services import estimates as E


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
    await engine.dispose()


async def _adult(env, email="ana@test.com") -> str:
    r = await env.client.post(
        "/api/auth/register",
        json={"email": email, "password": "s3cret123", "profile_type": "adult"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


async def _tarea(env, tok: str, *, est_minutes: int | None = 20, title="Deber de mates") -> int:
    r = await env.client.post(
        "/api/tasks",
        json={"category": "general", "title": title, "est_minutes": est_minutes},
        headers=_auth(tok),
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _sesiones(env, tok: str, task_id: int | None, minutos_reales: list[int], *, kind="homework", plan=20):
    for i, reales in enumerate(minutos_reales):
        r = await env.client.post(
            "/api/work-sessions",
            json={
                "kind": kind,
                "task_id": task_id,
                "planned_seconds": plan * 60,
                "actual_seconds": reales * 60,
                "completed_at": f"2026-09-{i + 1:02d}T18:00:00",
            },
            headers=_auth(tok),
        )
        assert r.status_code == 201, r.text


# ------------------------------------------------------------- reglas puras


def test_mediana_ignora_el_dia_malo():
    # El tercero fue un martes deambulante: la mediana no se mueve, la media sí.
    assert E._median([10, 10, 90]) == 10
    assert E._median([10, 20, 30, 90]) == 25


def test_redondeo_a_multiplos_de_5_y_topes():
    assert E._redondear(37) == 35
    assert E._redondear(23) == 25
    assert E._redondear(2) == E.MIN_SUGGESTED
    assert E._redondear(400) == E.MAX_SUGGESTED


# ----------------------------------------------------------------- endpoint


async def test_sin_historial_no_sugiere_nada(env):
    tok = await _adult(env)
    tarea = await _tarea(env, tok)
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    assert r.status_code == 200, r.text
    assert r.json()["suggested_minutes"] is None
    assert r.json()["samples"] == 0


async def test_con_dos_sesiones_no_sugiere_nada(env):
    # Menos de MIN_SAMPLES: corregir con dos días sería ruido.
    tok = await _adult(env)
    tarea = await _tarea(env, tok)
    await _sesiones(env, tok, tarea, [40, 45])
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    assert r.json()["suggested_minutes"] is None
    assert r.json()["samples"] == 2


async def test_tres_sesiones_sugieren_el_real_no_el_planificado(env):
    tok = await _adult(env)
    tarea = await _tarea(env, tok, est_minutes=20)
    await _sesiones(env, tok, tarea, [40, 45, 35])
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    body = r.json()
    assert body["suggested_minutes"] == 40
    assert body["based_on"] == "task"
    assert body["samples"] == 3
    assert body["planned_minutes"] == 20
    assert body["actual_minutes"] == 40


async def test_cae_al_tipo_cuando_la_tarea_no_tiene_historial_suficiente(env):
    tok = await _adult(env)
    tarea = await _tarea(env, tok, est_minutes=20)
    # Dos suyas y tres de otras tareas del mismo tipo.
    await _sesiones(env, tok, tarea, [50, 55])
    await _sesiones(env, tok, None, [30, 35, 32], kind="homework")
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    body = r.json()
    assert body["based_on"] == "kind"
    assert body["suggested_minutes"] == 35


async def test_la_tarea_gana_al_tipo_cuando_tiene_suficiente_historial(env):
    tok = await _adult(env)
    tarea = await _tarea(env, tok, est_minutes=20)
    await _sesiones(env, tok, tarea, [60, 60, 60])
    await _sesiones(env, tok, None, [10, 10, 10], kind="homework")
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    assert r.json()["based_on"] == "task"
    assert r.json()["suggested_minutes"] == 60


async def test_silencio_cuando_la_estimacion_ya_es_buena(env):
    # Real 22 min contra 20 estimados: no se dice nada. Una app que corrige por
    # corregir se gana un "ya lo decía" y se pierde para siempre.
    tok = await _adult(env)
    tarea = await _tarea(env, tok, est_minutes=20)
    await _sesiones(env, tok, tarea, [22, 21, 23])
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    body = r.json()
    assert body["suggested_minutes"] is None
    assert body["samples"] == 3
    # El dato se sigue exponiendo (redondeado a 5), pero no se propone nada.
    assert body["actual_minutes"] == 20


async def test_sin_estimate_usa_el_minimo_por_defecto_como_referencia(env):
    tok = await _adult(env)
    tarea = await _tarea(env, tok, est_minutes=None)
    await _sesiones(env, tok, tarea, [50, 50, 50])
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    # 25 por defecto contra 50 reales: sí merece mención.
    assert r.json()["suggested_minutes"] == 50


async def test_ignora_las_sesiones_de_menos_de_un_minuto(env):
    # Marcar y salir al instante no es "tardar 1 segundo": es no haber usado el
    # temporizador, y si se contaran, el plan se hundiría.
    tok = await _adult(env)
    tarea = await _tarea(env, tok, est_minutes=20)
    for _ in range(4):
        await env.client.post(
            "/api/work-sessions",
            json={"kind": "homework", "task_id": tarea, "planned_seconds": 1200, "actual_seconds": 1},
            headers=_auth(tok),
        )
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    assert r.json()["suggested_minutes"] is None
    assert r.json()["samples"] == 0


async def test_acepta_planned_minutes_para_items_de_estudio_sin_tarea(env):
    # Una sesión de estudio del plan no tiene task_id: su "estimación" la calcula
    # el plan, así que el llamador la pasa.
    tok = await _adult(env)
    await _sesiones(env, tok, None, [60, 65, 70], kind="study", plan=25)
    r = await env.client.get(
        "/api/work-sessions/estimate",
        params={"kind": "study", "planned_minutes": 25},
        headers=_auth(tok),
    )
    body = r.json()
    assert body["based_on"] == "kind"
    assert body["suggested_minutes"] == 65


async def test_rechaza_kind_inventado(env):
    tok = await _adult(env)
    r = await env.client.get("/api/work-sessions/estimate", params={"kind": "chores"}, headers=_auth(tok))
    assert r.status_code == 422


async def test_task_ajena_da_404_y_no_filtra_datos(env):
    tok = await _adult(env, "ana@test.com")
    otro = await _adult(env, "beto@test.com")
    tarea = await _tarea(env, otro, title="Tarea ajena")
    await _sesiones(env, otro, tarea, [90, 90, 90])
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    assert r.status_code == 404


async def test_no_acepta_estimacion_sin_autenticar(env):
    assert (await env.client.get("/api/work-sessions/estimate", params={"kind": "task"})).status_code == 401


async def test_el_historial_de_otro_no_cuenta(env):
    tok = await _adult(env, "ana@test.com")
    otro = await _adult(env, "beto@test.com")
    tarea = await _tarea(env, tok, est_minutes=20)
    await _sesiones(env, otro, None, [120, 120, 120], kind="homework")
    r = await env.client.get(
        "/api/work-sessions/estimate", params={"kind": "homework", "task_id": tarea}, headers=_auth(tok)
    )
    assert r.json()["suggested_minutes"] is None
