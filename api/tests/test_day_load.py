"""Tests de la carga del día: qué ocupa el día y si el plan cabe en el tope.

SQLite en memoria vía override de `get_db` (patrón ASGI, no toca la DB dev).
El foco está en la regla de no inventar números: una tarea sin estimación y sin
historial se cuenta como "no lo sabemos", no como 25 minutos. Y en que los tres
bloques (estudio repartido, tareas y extraescolares) se sumen sin pisarse.
"""

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.services.estimates import MIN_SAMPLES, kind_de_categoria, ritmos_reales
from app.services.load import day_load

# 2026-10-05 es lunes. Todos los tests usan esta semana como referencia.
LUNES = date(2026, 10, 5)


@pytest.fixture
async def env():
    maker = await make_session_factory()

    async def _get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield SimpleNamespace(client=c, maker=maker)
    app.dependency_overrides.clear()


async def _nino(env, email="nino@test.com") -> tuple[str, int]:
    """Alta real de niño (adulto + PIN) y devuelve su token y su id."""
    nombre = f"Nino {email}"
    adulto = await env.client.post(
        "/api/auth/register",
        json={"email": f"{email}-adulto", "password": "s3cret123", "profile_type": "adult"},
    )
    assert adulto.status_code in (200, 201), adulto.text
    cab = await env.client.post(
        "/api/auth/children",
        json={
            "display_name": nombre,
            "pin": "4821",
            "birth_date": "2015-01-01",
            "timezone": "UTC",
        },
        headers={"Authorization": f"Bearer {adulto.json()['token']}"},
    )
    assert cab.status_code in (200, 201), cab.text
    entrada = await env.client.post("/api/auth/child-login", json={"display_name": nombre, "pin": "4821"})
    assert entrada.status_code == 200, entrada.text
    tok = entrada.json()["token"]
    env.client.headers["Authorization"] = f"Bearer {tok}"
    return tok, cab.json()["id"]


async def _tarea(env, *, category="colegio-deberes", est_minutes=20, title="Mate", due_on=LUNES) -> int:
    r = await env.client.post(
        "/api/tasks",
        json={"category": category, "title": title, "est_minutes": est_minutes, "due_on": due_on.isoformat()},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _sesion(client, kind: str, task_id: int | None, *, plan=20, real=45) -> None:
    r = await client.post(
        "/api/work-sessions",
        json={
            "kind": kind,
            "task_id": task_id,
            "planned_seconds": plan * 60,
            "actual_seconds": real * 60,
        },
    )
    assert r.status_code in (200, 201), r.text


async def _extra(env, *, day=LUNES, inicio=time(17, 0), fin=time(18, 30), name="Natacion") -> None:
    r = await env.client.post(
        "/api/extracurriculars",
        json={
            "name": name,
            "day_of_week": day.weekday(),
            "start_time": inicio.isoformat(timespec="minutes"),
            "end_time": fin.isoformat(timespec="minutes"),
        },
    )
    assert r.status_code in (200, 201), r.text


class TestKindDeCategoria:
    def test_mapea_las_categorias_de_colegio(self):
        assert kind_de_categoria("colegio-deberes") == "homework"
        assert kind_de_categoria("colegio-trabajo") == "project"

    def test_cualquier_otra_categoria_es_task(self):
        assert kind_de_categoria("casa") == "task"
        assert kind_de_categoria("") == "task"


class TestRitmosReales:
    """El ritmo real que consume la carga del día (sin umbral de discrepancia)."""

    async def test_usa_el_historial_de_la_tarea(self, env):
        _, uid = await _nino(env, "a@test.com")
        task_id = await _tarea(env)
        for _ in range(MIN_SAMPLES):
            await _sesion(env.client, "homework", task_id, plan=20, real=45)

        async with env.maker() as db:
            from app.models.user import User

            user = await db.get(User, uid)
            assert await ritmos_reales(db, user, [("homework", task_id)]) == {("homework", task_id): 45}

    async def test_cae_al_tipo_si_la_tarea_no_tiene_historial(self, env):
        _, uid = await _nino(env, "b@test.com")
        tarea_a = await _tarea(env, title="A")
        tarea_b = await _tarea(env, title="B")
        for _ in range(MIN_SAMPLES):
            await _sesion(env.client, "homework", tarea_a, plan=20, real=40)

        async with env.maker() as db:
            from app.models.user import User

            user = await db.get(User, uid)
            ritmo = await ritmos_reales(db, user, [("homework", tarea_a), ("homework", tarea_b)])
            # Sin historial propio, B hereda el ritmo del tipo de trabajo.
            assert ritmo[("homework", tarea_a)] == 40
            assert ritmo[("homework", tarea_b)] == 40

    async def test_sin_historial_no_devuelve_nada(self, env):
        _, uid = await _nino(env, "c@test.com")
        task_id = await _tarea(env)

        async with env.maker() as db:
            from app.models.user import User

            user = await db.get(User, uid)
            assert await ritmos_reales(db, user, [("homework", task_id)]) == {}

    async def test_ignora_sesiones_de_menos_de_un_minuto(self, env):
        _, uid = await _nino(env, "d@test.com")
        task_id = await _tarea(env)
        for _ in range(MIN_SAMPLES):
            await _sesion(env.client, "homework", task_id, plan=0, real=0)

        async with env.maker() as db:
            from app.models.user import User

            user = await db.get(User, uid)
            assert await ritmos_reales(db, user, [("homework", task_id)]) == {}

    async def test_aisla_por_usuario(self, env):
        await _nino(env, "e@test.com")
        task_id = await _tarea(env)
        _, otro_uid = await _nino(env, "f@test.com")
        otro = env.client.headers["Authorization"]

        # `task_id` pertenece al primer niño, así que el segundo no puede ni
        # registrar sesiones sobre él (404) y su ritmo tampoco puede heredarlo.
        r = await env.client.post(
            "/api/work-sessions",
            json={
                "kind": "homework",
                "task_id": task_id,
                "planned_seconds": 1200,
                "actual_seconds": 3600,
            },
            headers={"Authorization": otro},
        )
        assert r.status_code == 404, r.text

        async with env.maker() as db:
            from app.models.user import User

            primero = await db.get(User, 1)
            assert await ritmos_reales(db, primero, [("homework", task_id)]) == {}
            segundo = await db.get(User, otro_uid)
            assert await ritmos_reales(db, segundo, [("homework", task_id)]) == {}


class TestCargaDelDia:
    async def test_sin_nada_pendiente_todo_es_cero(self, env):
        _, uid = await _nino(env)
        async with env.maker() as db:
            from app.models.user import User

            carga = await day_load(db, await db.get(User, uid), LUNES)
        assert carga.total_minutes == 0
        assert carga.tasks_pending == 0
        assert carga.study_minutes == 0
        assert carga.unplaced_study_minutes == 0

    async def test_suma_el_est_minutes_de_las_tareas(self, env):
        await _nino(env)
        await _tarea(env, est_minutes=20, title="Mate")
        await _tarea(env, est_minutes=15, title="Lengua")

        r = await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")
        assert r.status_code == 200
        body = r.json()
        assert body["task_minutes"] == 35
        assert body["tasks_pending"] == 2
        assert body["tasks_without_estimate"] == 0

    async def test_usa_el_ritmo_real_cuando_hay_historial(self, env):
        await _nino(env)
        task_id = await _tarea(env, est_minutes=20)
        for _ in range(MIN_SAMPLES):
            await _sesion(env.client, "homework", task_id, plan=20, real=45)

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        # 45 min reales, no los 20 estimados a mano.
        assert body["task_minutes"] == 45
        assert body["tasks_without_estimate"] == 0

    async def test_no_inventa_minutos_para_tareas_sin_estimacion(self, env):
        await _nino(env)
        await _tarea(env, category="general", est_minutes=None, title="Sin reloj")
        await _tarea(env, category="general", est_minutes=30, title="Con reloj")

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["task_minutes"] == 30
        assert body["tasks_without_estimate"] == 1

    async def test_cuenta_lo_atrasado_junto_a_lo_de_hoy(self, env):
        await _nino(env)
        await _tarea(env, est_minutes=25, due_on=LUNES - timedelta(days=3))

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["tasks_pending"] == 1
        assert body["task_minutes"] == 25

    async def test_no_cuenta_lo_ya_hecho(self, env):
        await _nino(env)
        task_id = await _tarea(env, est_minutes=25)
        r = await env.client.post(f"/api/tasks/{task_id}/complete", json={"done_on": LUNES.isoformat()})
        assert r.status_code in (200, 201), r.text

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["tasks_pending"] == 0
        assert body["task_minutes"] == 0

    async def test_no_cuenta_tareas_archivadas(self, env):
        await _nino(env)
        task_id = await _tarea(env, est_minutes=30)

        # `archived_at` se escribe directo porque no hay endpoint de archivo: lo
        # que importa aquí es que la carga lo Ignore, no el camino para llegar.
        async with env.maker() as db:
            from app.models.task import Task

            t = await db.get(Task, task_id)
            t.archived_at = datetime.now(UTC)
            await db.commit()

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["tasks_pending"] == 0
        assert body["task_minutes"] == 0

    async def test_las_extraescolares_cuentan_como_bloqueo(self, env):
        await _nino(env)
        await _extra(env, inicio=time(17, 0), fin=time(18, 30))

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["blocked_minutes"] == 90
        assert body["total_minutes"] == 90

    async def test_extraescolar_con_horas_invertidas_no_cuenta_negativo(self, env):
        await _nino(env)
        await _extra(env, inicio=time(19, 0), fin=time(8, 0), name="Raro")

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["blocked_minutes"] == 0

    async def test_total_suma_los_tres_bloques(self, env):
        await _nino(env)
        await _tarea(env, est_minutes=35)
        await _extra(env, inicio=time(17, 0), fin=time(18, 0))

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["total_minutes"] == body["task_minutes"] + body["study_minutes"] + body["blocked_minutes"]
        assert body["total_minutes"] == 35 + 0 + 60

    async def test_sin_tope_no_hay_exceso(self, env):
        await _nino(env)
        await _tarea(env, est_minutes=35)
        r = await env.client.patch("/api/auth/me", json={"study_max_minutes": 0})
        assert r.status_code == 200, r.text

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["daily_max_minutes"] == 0
        assert body["over_cap_minutes"] == 0

    async def test_aisla_por_usuario(self, env):
        await _nino(env, "uno@test.com")
        await _tarea(env, est_minutes=90)
        primero = env.client.headers["Authorization"]
        await _nino(env, "dos@test.com")

        # Cada niño ve solo sus propias tareas.
        suyo = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert suyo["task_minutes"] == 0 and suyo["tasks_pending"] == 0

        mio = (
            await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers={"Authorization": primero})
        ).json()
        assert mio["task_minutes"] == 90 and mio["tasks_pending"] == 1


class TestDayLoadEndpoint:
    async def test_requiere_token(self, env):
        assert (await env.client.get("/api/day-load")).status_code == 401

    async def test_por_defecto_es_hoy(self, env):
        await _nino(env)
        r = await env.client.get("/api/day-load")
        assert r.status_code == 200
        from datetime import UTC, datetime

        assert r.json()["date"] == datetime.now(UTC).date().isoformat()

    async def test_es_consulta_de_solo_lectura(self, env):
        await _nino(env)
        await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")
        pendientes = (await env.client.get("/api/pending")).json()
        assert pendientes["overdue"] == [] and pendientes["today"] == []

    async def test_el_tope_viene_del_perfil(self, env):
        await _nino(env)
        r = await env.client.patch("/api/auth/me", json={"study_max_minutes": 90})
        assert r.status_code == 200, r.text

        body = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}")).json()
        assert body["daily_max_minutes"] == 90