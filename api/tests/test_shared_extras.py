"""Tests de la extraescolar que también ocupa el día del adulto.

Dos cosas distintas se comprueban aquí:

- **Que entre lo que debe**: una extraescolar marcada como compartida ocupa el día
  del adulto, y una normal no. Sin esto la app mentía sobre la disponibilidad del
  adulto en cuanto tenía un niño con actividades.
- **Que no se cuenta dos veces**: los hermanos van cada uno con su fila. Para el
  adulto, llevar a los dos a la misma actividad es un solo viaje, no dos horas.
"""

from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.school import Extracurricular
from app.services.load import _minutos_unidos, _tramos_de_extras

# 2026-09-21 es lunes (weekday 0).
LUNES = date(2026, 9, 21)
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


def _cab(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _madre_con_ninos(env, nombres=("Lucía",)) -> tuple[dict, list[dict]]:
    r = await env.client.post(
        "/api/auth/register",
        json={"email": "mama@test.com", "password": "s3cret123", "profile_type": "adult", "display_name": "Mamá"},
    )
    assert r.status_code == 201, r.text
    madre = r.json()
    ninos = []
    for i, nombre in enumerate(nombres):
        n = await env.client.post(
            "/api/auth/children",
            json={"display_name": nombre, "pin": str(4821 + i), "birth_date": NACIMIENTO},
            headers=_cab(madre["token"]),
        )
        assert n.status_code == 201, n.text
        ninos.append(n.json())
    return madre, ninos


async def _token_de_nino(env, nombre: str, pin: str) -> str:
    r = await env.client.post("/api/auth/child-login", json={"display_name": nombre, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _extra(
    env,
    token: str,
    *,
    nombre: str = "Piano",
    inicio: str = "17:00",
    fin: str = "18:00",
    dia: int = 0,
    afecta: bool = True,
    **extra,
) -> dict:
    r = await env.client.post(
        "/api/extracurriculars",
        json={
            "name": nombre,
            "day_of_week": dia,
            "start_time": inicio,
            "end_time": fin,
            "affects_parent": afecta,
            **extra,
        },
        headers=_cab(token),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _carga(env, token: str, day: date = LUNES) -> dict:
    r = await env.client.get(f"/api/day-load?date={day.isoformat()}", headers=_cab(token))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ unión de horas


def test_unir_horas_vacias():
    assert _minutos_unidos([]) == 0


def test_unir_un_solo_tramo():
    assert _minutos_unidos([(1020, 1080)]) == 60


def test_unir_tramos_separados_suma():
    # 17:00-18:00 y 20:00-21:00: dos huecos distintos, 120 minutos.
    assert _minutos_unidos([(1020, 1080), (1200, 1260)]) == 120


def test_unir_tramos_que_se_pisan_no_repite():
    # 17:00-18:00 y 17:30-18:30 se solapan 30 min: 90, no 120.
    assert _minutos_unidos([(1020, 1080), (1050, 1110)]) == 90


def test_unir_tramos_iguales_no_repite():
    # Los dos hermanos en la misma actividad: una hora, no dos.
    assert _minutos_unidos([(1020, 1080), (1020, 1080)]) == 60


def test_unir_un_tramo_dentro_de_otro():
    assert _minutos_unidos([(1020, 1200), (1050, 1080)]) == 180


def test_unir_tramos_que_se_tocan():
    # 17:00-18:00 y 18:00-19:00 son 120 minutos seguidos: no hay hueco entre medias.
    assert _minutos_unidos([(1020, 1080), (1080, 1140)]) == 120


def test_un_tramo_invertido_no_cuenta():
    # `end_time` antes de `start_time` es dato corrupto y no debe sumar nada.
    assert _minutos_unidos([(1080, 1020)]) == 0


def test_unir_no_depende_del_orden_de_entrada():
    assert _minutos_unidos([(1200, 1260), (1020, 1080)]) == _minutos_unidos([(1020, 1080), (1200, 1260)])


# ------------------------------------------------------------------ qué entra en el día del adulto


async def test_la_extraescolar_compartida_ocupa_el_dia_del_adulto(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, afecta=True)

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 60
    assert carga["blocked_minutes"] == 60


async def test_la_extraescolar_solo_del_nino_no_ocupa_el_dia_del_adulto(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, afecta=False)

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 0
    assert carga["blocked_minutes"] == 0


async def test_la_extraescolar_del_nino_sigue_contando_en_su_propio_dia(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, afecta=False)

    carga = await _carga(env, token_nina)
    # No compartirla con el adulto no significa que el niño tenga el día libre.
    assert carga["extracurricular_minutes"] == 60


async def test_hermanos_en_la_misma_actividad_cuentan_una_hora(env):
    madre, (nina, nino) = await _madre_con_ninos(env, ("Lucía", "Dani"))
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    token_nino = await _token_de_nino(env, "Dani", "4822")
    await _extra(env, token_nina, inicio="17:00", fin="18:00")
    await _extra(env, token_nino, inicio="17:00", fin="18:00")

    carga = await _carga(env, madre["token"])
    # Dos filas, un solo viaje: 60, no 120.
    assert carga["extracurricular_minutes"] == 60


async def test_hermanos_en_actividades_distintas_suman(env):
    madre, (nina, nino) = await _madre_con_ninos(env, ("Lucía", "Dani"))
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    token_nino = await _token_de_nino(env, "Dani", "4822")
    await _extra(env, token_nina, nombre="Piano", inicio="17:00", fin="18:00")
    await _extra(env, token_nino, nombre="Natación", inicio="19:00", fin="20:00")

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 120


async def test_hermanos_con_horarios_que_se_pisan_se_unen(env):
    madre, (nina, nino) = await _madre_con_ninos(env, ("Lucía", "Dani"))
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    token_nino = await _token_de_nino(env, "Dani", "4822")
    await _extra(env, token_nina, inicio="17:00", fin="18:30")
    await _extra(env, token_nino, inicio="18:00", fin="19:00")

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 120  # de 17:00 a 19:00, sin huecos


async def test_una_extraescolar_de_otro_dia_no_cuenta(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, dia=1)  # martes

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 0


async def test_el_rango_de_fechas_tambien_filtra_la_compartida(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, start_on="2026-10-01")

    assert (await _carga(env, madre["token"]))["extracurricular_minutes"] == 0
    assert (await _carga(env, madre["token"], date(2026, 10, 5)))["extracurricular_minutes"] == 60


async def test_una_extraescolar_del_nino_no_le_sale_a_otra_familia(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina)

    otro = await env.client.post(
        "/api/auth/register",
        json={"email": "otro@test.com", "password": "s3cret123", "profile_type": "adult", "display_name": "Otro"},
    )
    carga = await _carga(env, otro.json()["token"])
    assert carga["extracurricular_minutes"] == 0


# ------------------------------------------------------------------ citas y extraescolares juntas


async def test_citas_y_extraescolares_se_suman_en_el_bloqueo(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, inicio="17:00", fin="18:00")
    await env.client.post(
        "/api/appointments",
        json={"title": "Médico", "date": LUNES.isoformat(), "start_time": "09:00:00", "end_time": "10:00:00"},
        headers=_cab(madre["token"]),
    )

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 60
    assert carga["appointment_minutes"] == 60
    assert carga["blocked_minutes"] == 120


async def test_una_cita_que_se_pisa_con_una_extraescolar_no_se_resta(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, inicio="17:00", fin="18:00")
    await env.client.post(
        "/api/appointments",
        json={"title": "Médico", "date": LUNES.isoformat(), "start_time": "17:30:00", "end_time": "18:30:00"},
        headers=_cab(madre["token"]),
    )

    carga = await _carga(env, madre["token"])
    # Se solapan, pero son dos compromisos distintos que el usuario ha creado: 120.
    assert carga["blocked_minutes"] == 120


# ------------------------------------------------------------------ API


async def test_por_defecto_una_extraescolar_no_afecta_al_adulto(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    r = await env.client.post(
        "/api/extracurriculars",
        json={"name": "Piano", "day_of_week": 0, "start_time": "17:00", "end_time": "18:00"},
        headers=_cab(token_nina),
    )
    assert r.status_code == 201, r.text
    assert r.json()["affects_parent"] is False


async def test_se_puede_marcar_compartida_y_desmarcar_despues(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    creada = await _extra(env, token_nina, afecta=True)
    assert creada["affects_parent"] is True

    r = await env.client.patch(
        f"/api/extracurriculars/{creada['id']}", json={"affects_parent": False}, headers=_cab(token_nina)
    )
    assert r.status_code == 200, r.text
    assert r.json()["affects_parent"] is False
    assert (await _carga(env, madre["token"]))["extracurricular_minutes"] == 0


async def test_se_puede_volver_a_marcar_compartida(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    creada = await _extra(env, token_nina, afecta=False)

    r = await env.client.patch(
        f"/api/extracurriculars/{creada['id']}", json={"affects_parent": True}, headers=_cab(token_nina)
    )
    assert r.json()["affects_parent"] is True
    assert (await _carga(env, madre["token"]))["extracurricular_minutes"] == 60


async def test_el_lista_de_extraescolares_incluye_el_campo(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, afecta=True)

    r = await env.client.get("/api/extracurriculars", headers=_cab(token_nina))
    assert r.status_code == 200
    assert [e["affects_parent"] for e in r.json()] == [True]


async def test_una_hora_invertida_no_ocupa_el_dia_del_adulto(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, inicio="18:00", fin="17:00")

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 0


async def test_el_dia_del_adulto_suma_extraescolar_compartida_y_propia(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, inicio="17:00", fin="18:00")
    await env.client.post(
        "/api/extracurriculars",
        json={
            "name": "Gimnasio",
            "day_of_week": 0,
            "start_time": "19:00",
            "end_time": "20:00",
            "affects_parent": True,
        },
        headers=_cab(madre["token"]),
    )

    carga = await _carga(env, madre["token"])
    assert carga["extracurricular_minutes"] == 120


async def test_una_extraescolar_propia_que_se_pisa_con_la_del_nino_no_repite(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, inicio="17:00", fin="18:00")
    await env.client.post(
        "/api/extracurriculars",
        json={
            "name": "Gimnasio",
            "day_of_week": 0,
            "start_time": "17:30",
            "end_time": "18:30",
            "affects_parent": True,
        },
        headers=_cab(madre["token"]),
    )

    carga = await _carga(env, madre["token"])
    # 17:00-18:30 seguidos: 90, no 120.
    assert carga["extracurricular_minutes"] == 90


async def test_el_dia_del_nino_no_une_su_propia_extraescolar_con_la_del_adulto(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía", "4821")
    await _extra(env, token_nina, inicio="17:00", fin="18:00")

    carga = await _carga(env, token_nina)
    assert carga["extracurricular_minutes"] == 60


def test_horas_de_extraescolar_como_tramos():
    # El ayudante lee una `time` de verdad, no texto: 17:30 son 1050 minutos.
    e = Extracurricular(id=1, user_id=1, name="x", day_of_week=0, start_time=time(17, 30), end_time=time(18, 45))
    assert _tramos_de_extras([e]) == [(1050, 1125)]