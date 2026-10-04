"""Tests del timeline del día.

La promesa importante de este endpoint es que **no se contradiga** con `day-load`: los
dos hablan del mismo día y tienen que dar el mismo número de minutos ocupados. Si
 divergieran, la interfaz mostraría dos cifras y no habría forma de saber cuál
 mentía. Eso es lo que se comprueba aquí.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app

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


async def _token_de_nino(env, nombre: str, pin: str = "4821") -> str:
    r = await env.client.post("/api/auth/child-login", json={"display_name": nombre, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _cita(env, token: str, **campos):
    cuerpo = {"title": "Médico", "date": LUNES.isoformat(), "start_time": "09:00:00", "end_time": "10:00:00"}
    cuerpo.update(campos)
    r = await env.client.post("/api/appointments", json=cuerpo, headers=_cab(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _extra(env, token: str, **campos):
    cuerpo = {
        "name": "Piano",
        "day_of_week": 0,
        "start_time": "17:00",
        "end_time": "18:00",
        "affects_parent": True,
    }
    cuerpo.update(campos)
    r = await env.client.post("/api/extracurriculars", json=cuerpo, headers=_cab(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _timeline(env, token: str, day: date = LUNES) -> dict:
    r = await env.client.get(f"/api/day-timeline?date={day.isoformat()}", headers=_cab(token))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ forma basica


async def test_un_dia_vacio_no_tiene_bloques(env):
    madre, _ = await _madre_con_ninos(env)
    tl = await _timeline(env, madre["token"])
    assert tl["blocks"] == []
    assert tl["blocked_minutes"] == 0
    # La ventana son 16 horas (07:00-23:00), todas libres.
    assert tl["free_minutes"] == 960


async def test_el_dia_devuelto_es_el_pedido(env):
    madre, _ = await _madre_con_ninos(env)
    tl = await _timeline(env, madre["token"], date(2026, 10, 5))
    assert tl["date"] == "2026-10-05"


async def test_sin_fecha_es_el_dia_de_hoy_del_usuario(env):
    madre, _ = await _madre_con_ninos(env)
    r = await env.client.get("/api/day-timeline", headers=_cab(madre["token"]))
    assert r.status_code == 200
    assert r.json()["date"] == date.today().isoformat()


# ------------------------------------------------------------------ bloques


async def test_una_cita_aparece_con_su_duracion(env):
    madre, _ = await _madre_con_ninos(env)
    cita = await _cita(env, madre["token"], place="Clínica")

    tl = await _timeline(env, madre["token"])
    assert len(tl["blocks"]) == 1
    bloque = tl["blocks"][0]
    assert bloque["kind"] == "cita"
    assert bloque["title"] == "Médico"
    assert bloque["place"] == "Clínica"
    assert bloque["minutes"] == 60
    assert bloque["cita_id"] == cita["id"]
    assert bloque["start"] == "09:00:00"
    assert bloque["end"] == "10:00:00"


async def test_los_bloques_vienen_en_orden_de_hora(env):
    madre, _ = await _madre_con_ninos(env)
    await _cita(env, madre["token"], title="Tarde", start_time="18:00", end_time="19:00")
    await _cita(env, madre["token"], title="Mañana", start_time="08:00", end_time="09:00")

    tl = await _timeline(env, madre["token"])
    assert [b["title"] for b in tl["blocks"]] == ["Mañana", "Tarde"]


async def test_una_cita_nombra_a_los_ninos_que_le_afectan(env):
    madre, (nina,) = await _madre_con_ninos(env)
    await _cita(env, madre["token"], affected_user_ids=[nina["id"]])

    bloque = (await _timeline(env, madre["token"]))["blocks"][0]
    assert bloque["affected"] == ["Lucía"]


async def test_una_extraescolar_compartida_sale_como_del_nino(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía")
    await _extra(env, token_nina)

    bloque = (await _timeline(env, madre["token"]))["blocks"][0]
    assert bloque["kind"] == "extraescolar_compartida"
    assert bloque["title"] == "Piano"
    assert bloque["affected"] == ["Lucía"]


async def test_una_extraescolar_sola_no_entra_en_el_dia_del_adulto(env):
    madre, (nina,) = await _madre_con_ninos(env)
    token_nina = await _token_de_nino(env, "Lucía")
    await _extra(env, token_nina, affects_parent=False)

    assert (await _timeline(env, madre["token"]))["blocks"] == []


async def test_la_extraescolar_propia_del_adulto_es_de_otro_tipo(env):
    madre, _ = await _madre_con_ninos(env)
    await _extra(env, madre["token"], name="Gimnasio")

    bloque = (await _timeline(env, madre["token"]))["blocks"][0]
    assert bloque["kind"] == "extraescolar"
    assert bloque["affected"] == []


async def test_los_hermanos_salen_por_separado_para_poder_nombrarlos(env):
    madre, (nina, nino) = await _madre_con_ninos(env, ("Lucía", "Dani"))
    await _extra(env, await _token_de_nino(env, "Lucía"), name="Piano")
    await _extra(env, await _token_de_nino(env, "Dani", "4822"), name="Piano")

    bloques = (await _timeline(env, madre["token"]))["blocks"]
    # Dos filas aunque el horario sea el mismo: son dos viajes que nombrar.
    assert len(bloques) == 2
    assert {b["affected"][0] for b in bloques} == {"Lucía", "Dani"}


# ------------------------------------------------------------------ coherencia con day-load


async def test_el_timeline_coincide_con_day_load_sin_nada_que_ocupe(env):
    madre, _ = await _madre_con_ninos(env)
    tl = await _timeline(env, madre["token"])
    carga = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(madre["token"]))).json()
    assert tl["blocked_minutes"] == carga["blocked_minutes"] == 0


async def test_el_timeline_coincide_con_day_load_con_citas(env):
    madre, (nina,) = await _madre_con_ninos(env)
    await _cita(env, madre["token"], start_time="09:00", end_time="10:30")
    await _cita(env, madre["token"], title="Cena fuera", start_time="21:00", end_time="23:00")

    tl = await _timeline(env, madre["token"])
    carga = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(madre["token"]))).json()
    assert tl["blocked_minutes"] == carga["blocked_minutes"] == 210  # 90 + 120


async def test_el_timeline_coincide_con_day_load_con_hijos_afectados(env):
    madre, (nina, nino) = await _madre_con_ninos(env, ("Lucía", "Dani"))
    # Una cita que afecta a los dos: 60 minutos, no 120.
    await _cita(env, madre["token"], affected_user_ids=[nina["id"], nino["id"]])

    tl = await _timeline(env, madre["token"])
    carga = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(madre["token"]))).json()
    assert tl["blocked_minutes"] == carga["blocked_minutes"] == 60


async def test_el_timeline_coincide_con_day_load_con_extraescolar_compartida(env):
    madre, (nina,) = await _madre_con_ninos(env)
    await _extra(env, await _token_de_nino(env, "Lucía"))

    tl = await _timeline(env, madre["token"])
    carga = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(madre["token"]))).json()
    assert tl["blocked_minutes"] == carga["blocked_minutes"] == 60


async def test_el_timeline_coincide_con_day_load_con_hermanos_en_la_misma_hora(env):
    madre, (nina, nino) = await _madre_con_ninos(env, ("Lucía", "Dani"))
    await _extra(env, await _token_de_nino(env, "Lucía"), start_time="17:00", end_time="18:00")
    await _extra(env, await _token_de_nino(env, "Dani", "4822"), start_time="17:00", end_time="18:00")

    tl = await _timeline(env, madre["token"])
    carga = (await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(madre["token"]))).json()
    # Dos filas en el timeline, 60 minutos de carga: uno no puede estar en dos sitios.
    assert len(tl["blocks"]) == 2
    assert tl["blocked_minutes"] == carga["blocked_minutes"] == 60


# ------------------------------------------------------------------ hueco libre


async def test_el_hueco_libre_baja_lo_que_se_ocupa(env):
    madre, _ = await _madre_con_ninos(env)
    await _cita(env, madre["token"], start_time="09:00", end_time="10:00")

    tl = await _timeline(env, madre["token"])
    assert tl["free_minutes"] == 960 - 60


async def test_el_hueco_libre_no_se_pone_negativo(env):
    madre, _ = await _madre_con_ninos(env)
    for i in range(12):
        await _cita(env, madre["token"], title=f"Cita {i}", start_time=f"{8 + i:02d}:00", end_time=f"{9 + i:02d}:00")

    tl = await _timeline(env, madre["token"])
    assert tl["free_minutes"] >= 0


async def test_el_hueco_libre_solo_mide_el_horario_en_juego(env):
    madre, _ = await _madre_con_ninos(env)
    # Una cita de madrugada sigue bloqueando, pero no come horas "de día". Las dos
    # cifras lo dicen: 60 minutos ocupados de verdad, y un hueco de día intacto.
    await _cita(env, madre["token"], start_time="02:00", end_time="03:00")

    tl = await _timeline(env, madre["token"])
    assert tl["blocked_minutes"] == 60
    assert tl["free_minutes"] == 960
    assert [(h["start"], h["end"]) for h in tl["huecos"]] == [("07:00:00", "23:00:00")]


# ------------------------------------------------------------------ permisos


async def test_otro_adulto_no_ve_el_timeline_de_este(env):
    madre, (nina,) = await _madre_con_ninos(env)
    await _cita(env, madre["token"])
    otro = (
        await env.client.post(
            "/api/auth/register",
            json={"email": "otro@test.com", "password": "s3cret123", "profile_type": "adult", "display_name": "Otro"},
        )
    ).json()

    tl = await _timeline(env, otro["token"])
    assert tl["blocks"] == []


async def test_hace_falta_autenticarse(env):
    r = await env.client.get("/api/day-timeline")
    assert r.status_code == 401


async def test_el_nino_ve_las_citas_que_le_afectan(env):
    madre, (nina,) = await _madre_con_ninos(env)
    await _cita(env, madre["token"], affected_user_ids=[nina["id"]])
    token_nina = await _token_de_nino(env, "Lucía")

    tl = await _timeline(env, token_nina)
    assert len(tl["blocks"]) == 1
    assert tl["blocks"][0]["title"] == "Médico"


async def test_el_nino_no_ve_la_extraescolar_de_otro_nino(env):
    madre, (nina, nino) = await _madre_con_ninos(env, ("Lucía", "Dani"))
    await _extra(env, await _token_de_nino(env, "Lucía", "4821"))
    token_dani = await _token_de_nino(env, "Dani", "4822")

    tl = await _timeline(env, token_dani)
    assert tl["blocks"] == []


async def test_una_cita_pasada_no_sale_en_hoy(env):
    madre, _ = await _madre_con_ninos(env)
    await _cita(env, madre["token"], date="2020-01-06")

    tl = await _timeline(env, madre["token"])
    assert tl["blocks"] == []


async def test_una_cita_semanal_solo_sale_en_su_dia_de_semana(env):
    madre, _ = await _madre_con_ninos(env)
    await _cita(env, madre["token"], date=LUNES.isoformat(), repeats_weekly=True)

    assert len((await _timeline(env, madre["token"], LUNES))["blocks"]) == 1
    assert (await _timeline(env, madre["token"], date(2026, 9, 22)))["blocks"] == []
    assert len((await _timeline(env, madre["token"], date(2026, 9, 28)))["blocks"]) == 1
# ------------------------------------------------------------------ comidas


async def _franja(env, token: str, slot: str, hora: str | None, enabled: bool = True):
    r = await env.client.patch(
        f"/api/menu/slots/{slot}",
        json={"enabled": enabled, "default_time": hora},
        headers=_cab(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _plato(env, token: str, dia: str, slot: str, texto: str):
    r = await env.client.put(f"/api/menu/plan/{dia}/{slot}", json={"free_text": texto}, headers=_cab(token))
    assert r.status_code == 200, r.text
    return r.json()


def _comidas(tl: dict) -> list[dict]:
    return [b for b in tl["blocks"] if b["kind"] == "comida"]


async def test_una_franja_activada_aparece_en_el_timeline(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "comida", "14:00:00")

    comidas = _comidas(await _timeline(env, madre["token"]))
    assert len(comidas) == 1
    assert comidas[0]["start"] == "14:00:00"
    # 60 min es la duración convenida de la franja "comida" (ver MINUTOS_POR_FRANJA).
    assert comidas[0]["end"] == "15:00:00"
    assert comidas[0]["minutes"] == 60
    assert comidas[0]["slot"] == "comida"


async def test_las_comidas_no_se_cobran_contra_la_carga_del_dia(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "desayuno", "08:00:00")
    await _franja(env, madre["token"], "comida", "14:00:00")

    tl = await _timeline(env, madre["token"])
    carga = await env.client.get(f"/api/day-load?date={LUNES.isoformat()}", headers=_cab(madre["token"]))

    # 30 + 60 de comida se ven en el día pero no restan estudio: es lo que se
    # decidió, y por eso `blocked_minutes` sigue a cero.
    assert len(_comidas(tl)) == 2
    assert tl["blocked_minutes"] == 0
    assert carga.json()["blocked_minutes"] == 0


async def test_la_comida_muestra_el_plato_planificado(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "comida", "14:00:00")
    await _plato(env, madre["token"], LUNES.isoformat(), "comida", "Lubina con patatas")

    comidas = _comidas(await _timeline(env, madre["token"]))
    assert comidas[0]["title"] == "Lubina con patatas"
    # El slot sigue estando: separates "cena" de "merienda" aunque el plato Repeita.
    assert comidas[0]["slot"] == "comida"


async def test_sin_plato_planificado_se_muestra_la_franja(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "cena", "21:00:00")

    comidas = _comidas(await _timeline(env, madre["token"]))
    assert comidas[0]["title"] == "Cena"


async def test_una_franja_activada_sin_hora_no_se_pinta(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "merienda", None)

    assert _comidas(await _timeline(env, madre["token"])) == []


async def test_una_franja_desactivada_no_se_pinta(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "cena", "21:00:00", enabled=False)

    assert _comidas(await _timeline(env, madre["token"])) == []


async def test_una_cena_tarde_se_recorta_en_lugar_de_dar_la_vuelta(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "cena", "23:40:00")

    comidas = _comidas(await _timeline(env, madre["token"]))
    assert len(comidas) == 1
    assert comidas[0]["start"] == "23:40:00"
    assert comidas[0]["minutes"] > 0
    assert comidas[0]["minutes"] <= 19


async def test_el_nino_no_ve_comidas_aunque_el_adulto_tenga_el_menu(env):
    madre, ninos = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "comida", "14:00:00")

    token = await _token_de_nino(env, ninos[0]["display_name"])
    assert _comidas(await _timeline(env, token)) == []


# ------------------------------------------------------------------ huecos


def _huecos(tl: dict) -> list[tuple[str, str]]:
    return [(h["start"], h["end"]) for h in tl["huecos"]]


async def test_sin_nada_ocupado_hay_un_solo_hueco_todo_el_dia(env):
    madre, _ = await _madre_con_ninos(env)

    tl = await _timeline(env, madre["token"])
    assert _huecos(tl) == [("07:00:00", "23:00:00")]
    assert tl["free_minutes"] == 960


async def test_un_bloque_a_medio_dia_parte_el_hueco_en_dos(env):
    madre, _ = await _madre_con_ninos(env)
    await _cita(env, madre["token"], start_time="12:00", end_time="13:00")

    tl = await _timeline(env, madre["token"])
    assert _huecos(tl) == [("07:00:00", "12:00:00"), ("13:00:00", "23:00:00")]
    assert tl["free_minutes"] == 300 + 600


async def test_los_bloques_solapados_dejan_un_solo_hueco(env):
    madre, _ = await _madre_con_ninos(env)
    await _cita(env, madre["token"], title="A", start_time="10:00", end_time="12:00")
    await _cita(env, madre["token"], title="B", start_time="11:00", end_time="13:00")

    tl = await _timeline(env, madre["token"])
    # El solape no se cuenta dos veces ni deja un hueco de un minuto en medio.
    assert _huecos(tl) == [("07:00:00", "10:00:00"), ("13:00:00", "23:00:00")]


async def test_un_bloque_que_empieza_antes_de_la_ventana_no_deja_hueco_antes(env):
    madre, _ = await _madre_con_ninos(env)
    await _cita(env, madre["token"], start_time="06:00", end_time="08:00")

    tl = await _timeline(env, madre["token"])
    assert _huecos(tl) == [("08:00:00", "23:00:00")]


async def test_las_comidas_parten_el_hueco_sin_cobrarlo(env):
    madre, _ = await _madre_con_ninos(env)
    await _franja(env, madre["token"], "comida", "14:00:00")

    tl = await _timeline(env, madre["token"])
    # Se ve que a las dos no hay nada que colocar...
    assert _huecos(tl) == [("07:00:00", "14:00:00"), ("15:00:00", "23:00:00")]
    # ...pero el rato de comer no se ha cobrado contra el tiempo de estudio.
    assert tl["blocked_minutes"] == 0


async def test_los_minutos_libres_suman_los_huecos(env):
    madre, _ = await _madre_con_ninos(env, ("Lucía", "Dani"))
    await _cita(env, madre["token"], start_time="09:00", end_time="10:30")
    await _extra(env, madre["token"], day_of_week=0, start_time="17:00", end_time="18:30")
    await _franja(env, madre["token"], "comida", "14:00:00")
    await _franja(env, madre["token"], "merienda", "17:45:00")

    tl = await _timeline(env, madre["token"])
    assert sum(h["minutes"] for h in tl["huecos"]) == tl["free_minutes"]
