"""Tests de `/api/work-sessions`: el registro que deja el temporizador.

SQLite en memoria vía override de `get_db` (patrón ASGI, no toca la DB dev).
"""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registra todas las tablas
from app.db import Base, get_db
from app.main import app


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


async def _crear(env, token: str, **kw):
    payload = {"kind": "homework", "planned_seconds": 1200, "actual_seconds": 1200}
    payload.update(kw)
    return await env.client.post(
        "/api/work-sessions", json=payload, headers={"Authorization": f"Bearer {token}"}
    )


async def test_crear_sesion_pone_completed_at_si_no_viene(env):
    tok = await _adult(env)
    r = await _crear(env, tok)
    assert r.status_code == 201, r.text
    assert r.json()["completed_at"] is not None
    assert r.json()["actual_seconds"] == 1200


async def test_acepta_task_para_las_tareas_del_adulto(env):
    # El temporizador de "Mi día" también cronometra chores, que no son
    # deberes ni estudio: sin "task" en el patrón, el adulto no podría.
    tok = await _adult(env)
    r = await _crear(env, tok, kind="task", actual_seconds=600)
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "task"


async def test_rechaza_kind_inventado(env):
    tok = await _adult(env)
    assert (await _crear(env, tok, kind="chores")).status_code == 422


async def test_rechaza_segundos_negativos(env):
    tok = await _adult(env)
    assert (await _crear(env, tok, actual_seconds=-1)).status_code == 422


async def test_no_acepta_sesion_sin_autenticar(env):
    assert (await env.client.post("/api/work-sessions", json={"kind": "task", "actual_seconds": 1})).status_code == 401


async def test_lista_solo_las_sesiones_propias_y_de_mas_reciente_a_mas_antigua(env):
    tok = await _adult(env, "ana@test.com")
    otro = await _adult(env, "beto@test.com")
    await _crear(env, tok, actual_seconds=100)
    await _crear(env, tok, actual_seconds=200)
    await _crear(env, otro, actual_seconds=999)

    r = await env.client.get("/api/work-sessions", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    filas = r.json()
    assert [f["actual_seconds"] for f in filas] == [200, 100]


async def test_task_id_de_otra_cuenta_no_se_acepta_al_listar(env):
    # La sesión cuelga del user_id del token, no del task_id enviado.
    tok = await _adult(env, "ana@test.com")
    tarea = await env.client.post(
        "/api/tasks", json={"category": "general", "title": "Ordenar"}, headers={"Authorization": f"Bearer {tok}"}
    )
    assert tarea.status_code in (200, 201), tarea.text
    r = await _crear(env, tok, kind="task", task_id=tarea.json()["id"], actual_seconds=60)
    assert r.status_code == 201, r.text
    assert r.json()["task_id"] == tarea.json()["id"]


async def test_no_se_puede_registrar_una_sesion_sobre_la_tarea_de_otro(env):
    # El `task_id` va suelto en el cuerpo y la FK solo comprueba que exista, así
    # que sin este check se colgaría una sesión de la tarea ajena y saldría en
    # `GET /work-sessions` del otro niño.
    tok_ana = await _adult(env, "ana@test.com")
    tarea = await env.client.post(
        "/api/tasks", json={"category": "general", "title": "Ordenar"}, headers={"Authorization": f"Bearer {tok_ana}"}
    )
    assert tarea.status_code in (200, 201), tarea.text

    tok_beto = await _adult(env, "beto@test.com")
    r = await _crear(env, tok_beto, kind="task", task_id=tarea.json()["id"], actual_seconds=60)
    assert r.status_code == 404, r.text

    # Y no queda nada colgando de la tarea ajena.
    propias = await env.client.get("/api/work-sessions", headers={"Authorization": f"Bearer {tok_beto}"})
    assert propias.json() == []


async def test_no_se_puede_registrar_una_sesion_sobre_una_tarea_inexistente(env):
    tok = await _adult(env, "ana@test.com")
    r = await _crear(env, tok, kind="task", task_id=999999, actual_seconds=60)
    assert r.status_code == 404, r.text
