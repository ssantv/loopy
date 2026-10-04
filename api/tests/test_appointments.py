"""Tests de citas: repetición, reparto entre personas y permisos.

Lo que se comprueba aquí es lo que no se ve en la interfaz y donde está el riesgo:

- **Cuándo** existe una cita (puntual, semanal, hasta cuándo) y cuándo no.
- **A quién** bloquea: una cita de un niño lo bloquea a él, no solo al adulto.
- **Cuánto** cuenta: un cumpleaños que afecta a tres personas es una hora de día
  ocupado, no tres. Sumar por persona haría que los días con más gente parecieran
  los más llenos, que es justo al revés de la realidad.
- **Quién** puede crearlas y si se puede colgar a un niño ajeno.
"""

from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.appointment import Appointment
from app.services.appointments import citas_de, minutos_bloqueados, ocurre_en

# 2026-09-21 es lunes. Todo el módulo se apoya en esa fecha.
LUNES = date(2026, 9, 21)
MARTES = date(2026, 9, 22)
MIERCOLES = date(2026, 9, 23)
JUEVES = date(2026, 9, 24)
NACIMIENTO = "2018-05-04"


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


async def _adulto(env, email: str = "mama@test.com", nombre: str = "Mamá") -> dict:
    r = await env.client.post(
        "/api/auth/register",
        json={"email": email, "password": "s3cret123", "profile_type": "adult", "display_name": nombre},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _cab(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _nino(env, token: str, nombre: str, pin: str = "4821") -> dict:
    """Crea un niño y devuelve su user tal cual lo devuelve la API."""
    r = await env.client.post(
        "/api/auth/children",
        json={"display_name": nombre, "pin": pin, "birth_date": NACIMIENTO},
        headers=_cab(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _token_de_nino(env, nombre: str, pin: str = "4821") -> str:
    r = await env.client.post("/api/auth/child-login", json={"display_name": nombre, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _crear_cita(env, token: str, **campos) -> dict:
    cuerpo = {"title": "Médico", "date": LUNES.isoformat(), "start_time": "09:00:00", "end_time": "10:00:00"}
    cuerpo.update(campos)
    r = await env.client.post("/api/appointments", json=cuerpo, headers=_cab(token))
    assert r.status_code == 201, r.text
    return r.json()


def _cita(**kw) -> Appointment:
    """Cita a pelo, sin BD, para probar la resolución de fechas."""
    base = {
        "id": 1,
        "owner_id": 1,
        "title": "Dentista",
        "place": None,
        "notes": None,
        "first_on": LUNES,
        "start_time": time(17, 0),
        "end_time": time(18, 0),
        "repeats_weekly": False,
        "until": None,
    }
    return Appointment(**{**base, **kw})


# ------------------------------------------------------------------ cuándo existe


def test_una_cita_puntual_solo_existe_su_dia():
    cita = _cita(first_on=JUEVES)
    assert ocurre_en(cita, JUEVES)
    assert not ocurre_en(cita, MARTES)
    assert not ocurre_en(cita, date(2026, 9, 28))


def test_una_cita_puntual_no_existe_en_dias_anteriores():
    # El pasado no se rellena solo: nadie ha dicho que el dentista fuera el lunes
    # pasado aunque la fila se haya creado con una fecha anterior por error.
    cita = _cita(first_on=JUEVES)
    assert not ocurre_en(cita, LUNES)
    assert not ocurre_en(cita, MARTES)


def test_una_cita_semanal_repite_en_su_dia_de_semana():
    cita = _cita(first_on=LUNES, repeats_weekly=True)
    assert ocurre_en(cita, LUNES)
    assert not ocurre_en(cita, MARTES)
    assert ocurre_en(cita, date(2026, 9, 28))  # siguiente lunes
    assert ocurre_en(cita, date(2026, 12, 21))  # tres meses después


def test_una_cita_semanal_para_en_until():
    cita = _cita(first_on=LUNES, repeats_weekly=True, until=MIERCOLES)
    assert ocurre_en(cita, LUNES)
    assert not ocurre_en(cita, date(2026, 9, 28))  # el lunes siguiente ya está fuera


def test_minutos_de_una_cita():
    assert _cita(start_time=time(17, 0), end_time=time(18, 30)).minutos == 90
    assert _cita(start_time=time(9, 0), end_time=time(9, 45)).minutos == 45


def test_una_hora_invertida_no_es_un_bloque_negativo():
    # `end_time` antes de `start_time` es dato corrupto, no "ocupa la noche".
    assert _cita(start_time=time(18, 0), end_time=time(17, 0)).minutos == 0


# ------------------------------------------------------------------ creación


async def test_el_adulto_crea_una_cita_para_si_mismo(env):
    madre = await _adulto(env)
    cita = await _crear_cita(env, madre["token"])
    assert cita["minutes"] == 60
    assert cita["affected"] == []
    assert cita["owner_id"] == madre["user"]["id"]


async def test_la_cita_afecta_a_los_ninos_que_se_elijan(env):
    madre = await _adulto(env)
    nina = await _nino(env, madre["token"], "Lucía")
    nino = await _nino(env, madre["token"], "Dani", pin="1111")

    cita = await _crear_cita(env, madre["token"], affected_user_ids=[nina["id"], nino["id"]])
    assert {a["display_name"] for a in cita["affected"]} == {"Lucía", "Dani"}


async def test_no_se_puede_colgar_el_nino_de_otra_cuenta(env):
    madre = await _adulto(env, "mama@test.com")
    nina = await _nino(env, madre["token"], "Lucía")
    otro = await _adulto(env, "otro@test.com", "Otro adulto")

    r = await env.client.post(
        "/api/appointments",
        json={
            "title": "Cita ajena",
            "date": LUNES.isoformat(),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
            "affected_user_ids": [nina["id"]],
        },
        headers=_cab(otro["token"]),
    )
    # 422 y no 403: el id existe, lo que no es válido es usarlo aquí.
    assert r.status_code == 422, r.text


async def test_un_nino_no_crea_citas(env):
    madre = await _adulto(env)
    await _nino(env, madre["token"], "Lucía")
    token_nino = await _token_de_nino(env, "Lucía")

    r = await env.client.post(
        "/api/appointments",
        json={"title": "Yo quiero", "date": LUNES.isoformat(), "start_time": "09:00:00", "end_time": "10:00:00"},
        headers=_cab(token_nino),
    )
    assert r.status_code == 403


async def test_no_se_acepta_una_cita_que_termina_antes_de_empezar(env):
    madre = await _adulto(env)
    r = await env.client.post(
        "/api/appointments",
        json={"title": "Imposible", "date": LUNES.isoformat(), "start_time": "10:00:00", "end_time": "09:00:00"},
        headers=_cab(madre["token"]),
    )
    assert r.status_code == 422


async def test_until_sin_repeticion_se_rechaza(env):
    madre = await _adulto(env)
    r = await env.client.post(
        "/api/appointments",
        json={
            "title": "Raro",
            "date": LUNES.isoformat(),
            "start_time": "10:00:00",
            "end_time": "11:00:00",
            "repeats_weekly": False,
            "until": JUEVES.isoformat(),
        },
        headers=_cab(madre["token"]),
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ reparto


async def test_la_cita_bloquea_tambien_el_dia_del_nino(env):
    madre = await _adulto(env)
    nina = await _nino(env, madre["token"], "Lucía")
    await _crear_cita(env, madre["token"], start_time="17:00:00", end_time="18:00:00", affected_user_ids=[nina["id"]])

    async with env.maker() as db:
        del_mama = await citas_de(db, madre["user"]["id"], LUNES)
        # La niña tiene que ver la cita en su propio día: es la que va al dentista.
        del_nino = await citas_de(db, nina["id"], LUNES)

    assert [o.cita.title for o in del_mama] == ["Médico"]
    assert [o.cita.title for o in del_nino] == ["Médico"]
    assert minutos_bloqueados(del_nino) == 60


async def test_una_cita_que_afecta_a_tres_cuenta_una_hora(env):
    madre = await _adulto(env)
    nina = await _nino(env, madre["token"], "Lucía")
    nino = await _nino(env, madre["token"], "Dani", pin="1111")
    await _crear_cita(
        env,
        madre["token"],
        title="Cumpleaños",
        start_time="18:00:00",
        end_time="19:00:00",
        affected_user_ids=[nina["id"], nino["id"]],
    )

    async with env.maker() as db:
        del_mama = await citas_de(db, madre["user"]["id"], LUNES)
        del_nino = await citas_de(db, nina["id"], LUNES)

    # Ni 60 ni 180: una hora. El cumpleaños ocupa el día una vez.
    assert minutos_bloqueados(del_mama) == 60
    assert minutos_bloqueados(del_nino) == 60
    assert len(del_mama) == 1


async def test_una_cita_no_sale_dos_veces_por_ser_creadora_y_afectada(env):
    madre = await _adulto(env)
    nina = await _nino(env, madre["token"], "Lucía")
    cita = await _crear_cita(
        env, madre["token"], repeats_weekly=True, affected_user_ids=[nina["id"]]
    )

    r = await env.client.get(f"/api/appointments/day/{LUNES.isoformat()}", headers=_cab(madre["token"]))
    assert r.status_code == 200
    assert [c["id"] for c in r.json()] == [cita["id"]]


async def test_el_nino_ve_las_citas_que_le_afectan(env):
    madre = await _adulto(env)
    nina = await _nino(env, madre["token"], "Lucía")
    await _crear_cita(env, madre["token"], affected_user_ids=[nina["id"]])
    token_nino = await _token_de_nino(env, "Lucía")

    r = await env.client.get(f"/api/appointments/day/{LUNES.isoformat()}", headers=_cab(token_nino))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


# ------------------------------------------------------------------ carga diaria


async def test_la_carga_del_adulto_suma_las_citas(env):
    madre = await _adulto(env)
    await _crear_cita(env, madre["token"], start_time="09:00:00", end_time="10:30:00")

    carga = await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(madre["token"]))
    assert carga.status_code == 200, carga.text
    assert carga.json()["appointment_minutes"] == 90
    assert carga.json()["appointments_count"] == 1
    assert carga.json()["blocked_minutes"] == 90


async def test_el_nino_ve_en_su_carga_la_cita_que_le_afecta(env):
    madre = await _adulto(env)
    nina = await _nino(env, madre["token"], "Lucía")
    await _crear_cita(
        env, madre["token"], start_time="17:00:00", end_time="18:00:00", affected_user_ids=[nina["id"]]
    )
    token_nino = await _token_de_nino(env, "Lucía")

    carga = await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(token_nino))
    assert carga.json()["appointment_minutes"] == 60


async def test_una_cita_que_no_afecta_al_nino_no_entra_en_su_carga(env):
    madre = await _adulto(env)
    await _nino(env, madre["token"], "Lucía")
    await _crear_cita(env, madre["token"])
    token_nino = await _token_de_nino(env, "Lucía")

    carga = await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(token_nino))
    assert carga.json()["appointment_minutes"] == 0


# ------------------------------------------------------------------ edición y borrado


async def test_editar_quita_a_los_afectados(env):
    madre = await _adulto(env)
    nina = await _nino(env, madre["token"], "Lucía")
    cita = await _crear_cita(env, madre["token"], affected_user_ids=[nina["id"]])

    r = await env.client.patch(
        f"/api/appointments/{cita['id']}", json={"affected_user_ids": []}, headers=_cab(madre["token"])
    )
    assert r.status_code == 200, r.text
    assert r.json()["affected"] == []

    async with env.maker() as db:
        assert await citas_de(db, nina["id"], LUNES) == []


async def test_editar_mueve_el_bloque_de_hora(env):
    madre = await _adulto(env)
    cita = await _crear_cita(env, madre["token"])

    r = await env.client.patch(
        f"/api/appointments/{cita['id']}",
        json={"start_time": "11:00:00", "end_time": "12:30:00"},
        headers=_cab(madre["token"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["minutes"] == 90


async def test_editar_a_una_hora_invertida_se_rechaza(env):
    madre = await _adulto(env)
    cita = await _crear_cita(env, madre["token"])

    r = await env.client.patch(
        f"/api/appointments/{cita['id']}",
        json={"start_time": "20:00:00", "end_time": "08:00:00"},
        headers=_cab(madre["token"]),
    )
    assert r.status_code == 422


async def test_borrar_la_cita_libera_el_dia(env):
    madre = await _adulto(env)
    cita = await _crear_cita(env, madre["token"])

    assert (await env.client.delete(f"/api/appointments/{cita['id']}", headers=_cab(madre["token"]))).status_code == 204

    async with env.maker() as db:
        assert await citas_de(db, madre["user"]["id"], LUNES) == []


async def test_una_cita_de_otro_no_se_puede_tocar(env):
    madre = await _adulto(env, "mama@test.com")
    cita = await _crear_cita(env, madre["token"])
    otro = await _adulto(env, "otro@test.com", "Otro adulto")

    r = await env.client.patch(
        f"/api/appointments/{cita['id']}", json={"title": "Secuestrada"}, headers=_cab(otro["token"])
    )
    # 404 y no 403: ni siquiera se confirma que la cita existe.
    assert r.status_code == 404


async def test_una_cita_de_otro_no_se_puede_borrar(env):
    madre = await _adulto(env, "mama@test.com")
    cita = await _crear_cita(env, madre["token"])
    otro = await _adulto(env, "otro@test.com", "Otro adulto")

    r = await env.client.delete(f"/api/appointments/{cita['id']}", headers=_cab(otro["token"]))
    assert r.status_code == 404


async def test_una_cita_no_se_edita_si_pasa_a_terminar_antes_de_empezar(env):
    madre = await _adulto(env)
    cita = await _crear_cita(env, madre["token"], start_time="17:00:00", end_time="19:00:00")

    r = await env.client.patch(
        f"/api/appointments/{cita['id']}", json={"end_time": "16:00:00"}, headers=_cab(madre["token"])
    )
    assert r.status_code == 422


# ------------------------------------------------------------------ listado


async def test_el_listado_devuelve_cada_cita_una_sola_vez(env):
    madre = await _adulto(env)
    await _crear_cita(env, madre["token"], repeats_weekly=True)

    r = await env.client.get(
        f"/api/appointments?desde={LUNES.isoformat()}&hasta={MIERCOLES.isoformat()}",
        headers=_cab(madre["token"]),
    )
    assert r.status_code == 200, r.text
    # Tres días, una cita semanal: una fila, no tres.
    assert len(r.json()) == 1


async def test_el_listado_solo_ensea_las_citas_del_rango(env):
    madre = await _adulto(env)
    await _crear_cita(env, madre["token"], date=JUEVES.isoformat())

    r = await env.client.get(
        f"/api/appointments?desde={LUNES.isoformat()}&hasta={MARTES.isoformat()}",
        headers=_cab(madre["token"]),
    )
    assert r.json() == []


async def test_una_cita_ajena_no_aparece_en_el_listado_de_otro(env):
    madre = await _adulto(env, "mama@test.com")
    await _crear_cita(env, madre["token"])
    otro = await _adulto(env, "otro@test.com", "Otro adulto")

    r = await env.client.get(
        f"/api/appointments?desde={LUNES.isoformat()}&hasta={MARTES.isoformat()}",
        headers=_cab(otro["token"]),
    )
    assert r.json() == []


async def test_sin_rango_el_listado_usa_el_hoy_del_usuario(env, monkeypatch):
    """Sin rango, el listado arranca en el día del usuario y no en el del servidor.

    Es lo que separa esta pantalla de un listado "vacío" a las 20:00 en Chile: el
    servidor va 3 o 4 horas por delante y su fecha ya es la de mañana.
    """
    madre = await _adulto(env)
    # Se fija el reloj del usuario a un día que el servidor no está mirando: así la
    # prueba no depende de la hora a la que se ejecute.
    monkeypatch.setattr("app.routers.appointment.hoy", lambda user: JUEVES)
    await _crear_cita(env, madre["token"], date=JUEVES.isoformat())

    r = await env.client.get("/api/appointments", headers=_cab(madre["token"]))
    assert r.status_code == 200, r.text
    assert [c["title"] for c in r.json()] == ["Médico"]