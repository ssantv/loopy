"""Tests de la tarea colocada en un hueco: lo que cuesta ponerla y lo que devuelve.

Cierra el pendiente 11 ("organiza tu tarde"). Lo que se comprueba es lo que no se ve
en la interfaz y donde está el riesgo:

- **Que colocar parte el hueco de verdad**: un hueco de una hora con una tarea de 25
  minutos dentro son dos huecos (17:00–17:25 y 17:25–18:00), no uno de 35 minutos.
- **Que la tarea colocada ocupa**: suma a `blocked_minutes` y el día se queda con
  menos rato libre, pero la tarea sigue contando como pendiente en `task_minutes`.
- **Que no se cuenta dos veces**: una tarea de 25 colocada son 25 minutos de trabajo
  y 25 de rato ocupado, no 50. `total_minutes` lo resta.
- **Que el niño también puede**: el pendiente era del adulto, pero la línea es suya
  y colocar un deber no es una decisión de mayor.
- **Que quitar no borra**: quitar la colocación deja la tarea viva y pendiente.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app

# 2026-09-21 es lunes.
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


async def _adulto(env, email: str = "mama@test.com", tz: str = "UTC") -> dict:
    r = await env.client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "s3cret123",
            "profile_type": "adult",
            "display_name": "Mamá",
            "timezone": tz,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _token_de_nino(env, token: str, nombre: str = "Lucía", pin: str = "4821") -> str:
    r = await env.client.post(
        "/api/auth/children",
        json={"display_name": nombre, "pin": pin, "birth_date": NACIMIENTO},
        headers=_cab(token),
    )
    assert r.status_code == 201, r.text
    r = await env.client.post("/api/auth/child-login", json={"display_name": nombre, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def _crear_tarea(env, token: str, titulo: str = "Poner la lavadora", **campos) -> dict:
    # `due_on` a propósito: es lo que hace que una tarea puntual tenga ocurrencia
    # pendiente y entre en "qué toca hoy" y en `task_minutes`, que es justo lo que hay
    # que medir aquí.
    cuerpo = {"title": titulo, "category": "hogar", "due_on": LUNES.isoformat()}
    cuerpo.update(campos)
    r = await env.client.post("/api/tasks", json=cuerpo, headers=_cab(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _colocar(env, token: str, task_id: int, hora: str, minutos: int | None = None) -> dict:
    """Coloca como lo haría el navegador: en UTC.

    `new Date(2026, 8, 21, 18, 0).toISOString()` manda la hora **del servidor** del
    navegador, no la del usuario, así que el cliente siempre acaba enviando UTC. Los
    tests mandan lo mismo para no estar probando una forma de llamada que la
    aplicación no usa.
    """
    cuerpo: dict = {"start": f"{LUNES.isoformat()}T{hora}:00Z"}
    if minutos is not None:
        cuerpo["minutes"] = minutos
    r = await env.client.post(f"/api/tasks/{task_id}/place", json=cuerpo, headers=_cab(token))
    assert r.status_code == 200, r.text
    return r.json()


async def _linea(env, token: str) -> dict:
    r = await env.client.get(
        "/api/day-timeline", params={"date": LUNES.isoformat()}, headers=_cab(token)
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _carga(env, token: str) -> dict:
    r = await env.client.get(
        "/api/day-load", params={"date": LUNES.isoformat()}, headers=_cab(token)
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- colocar


async def test_una_tarea_sin_colocar_no_aparece_en_la_linea(env):
    a = await _adulto(env)
    await _crear_tarea(env, a["token"])

    linea = await _linea(env, a["token"])
    assert not [b for b in linea["blocks"] if b["kind"] == "tarea"]
    assert linea["blocked_minutes"] == 0


async def test_colocar_una_tarea_la_parte_el_hueco_en_dos(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])

    await _colocar(env, a["token"], t["id"], "17:00", 25)

    linea = await _linea(env, a["token"])
    # El hueco de la tarde (07:00–23:00) se parte en tres: antes, el de la tarea, y
    # el de después. Sin contar el de antes y el de después, el reparto no cuadra.
    huecos = [(h["start"], h["end"]) for h in linea["huecos"]]
    assert ("07:00:00", "17:00:00") in huecos
    assert ("17:25:00", "23:00:00") in huecos
    # Y no queda un hueco que cruce por delante de la tarea.
    assert not any(s == "17:00:00" and e == "23:00:00" for s, e in huecos)


async def test_la_tarea_colocada_aparece_como_bloque_con_su_rato(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])

    await _colocar(env, a["token"], t["id"], "17:00", 25)

    linea = await _linea(env, a["token"])
    bloque = next(b for b in linea["blocks"] if b["kind"] == "tarea")
    assert bloque["title"] == "Poner la lavadora"
    assert bloque["start"] == "17:00:00"
    assert bloque["end"] == "17:25:00"
    assert bloque["minutes"] == 25
    assert bloque["task_id"] == t["id"]
    assert bloque["done"] is False


async def test_la_tarea_colocada_ocupa_el_dia(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])

    await _colocar(env, a["token"], t["id"], "17:00", 25)

    linea = await _linea(env, a["token"])
    carga = await _carga(env, a["token"])
    assert linea["blocked_minutes"] == 25
    # Las dos cifras tienen que salir del mismo sitio: si el timeline contara de una
    # manera y la carga de otra, la pantalla enseñaría dos números incompatibles.
    assert carga["blocked_minutes"] == linea["blocked_minutes"]
    assert carga["placed_minutes"] == 25
    # El hueco se recorta en la misma medida que ocupa el bloque.
    assert linea["blocked_minutes"] + linea["free_minutes"] == 16 * 60


async def test_una_tarea_colocada_no_se_cuenta_dos_veces_en_el_total(env):
    a = await _adulto(env)
    # Con `est_minutes` la tarea suma como trabajo pendiente, así que su tramo
    # colocado es el solape que hay que restar: 25 + 25 − 25 = 25.
    t = await _crear_tarea(env, a["token"], est_minutes=25)

    await _colocar(env, a["token"], t["id"], "17:00", 25)

    carga = await _carga(env, a["token"])
    assert carga["task_minutes"] == 25
    assert carga["blocked_minutes"] == 25
    assert carga["placed_minutes"] == 25
    assert carga["total_minutes"] == 25


async def test_una_tarea_colocada_sin_estimar_no_se_borra_de_la_cuenta(env):
    """Colocar una tarea sin estimación ocupa el rato, y ese rato tiene que contar.

    Es el caso normal de una tarea del adulto, que casi nunca trae `est_minutes`. Como
    no suma trabajo pendiente, su duración no está en ningún otro sitio del total: si
    `total_minutes` restara los 25 colocados, el día se quedaría en 0 y diría que no
    hay nada que hacer cuando hay media hora de rato comprometida.
    """
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])

    await _colocar(env, a["token"], t["id"], "17:00", 25)

    carga = await _carga(env, a["token"])
    assert carga["tasks_without_estimate"] == 1
    assert carga["task_minutes"] == 0
    assert carga["blocked_minutes"] == 25
    # El rato colocado sigue en la cuenta, restado lo que no se había sumado.
    assert carga["total_minutes"] == 25


async def test_la_hora_se_lee_en_la_zona_del_usuario_y_no_en_la_del_servidor(env):
    """La línea tiene que mostrar la hora que el usuario quiso, esté donde esté el servidor.

    SQLite tira el offset al guardar, así que una `planned_start` vuelve de la base sin
    zona. Si al releerla se asumiera la hora local **de la máquina**, en un servidor de
    Madrid una tarea colocada a las 18:00 se escondería a las 16:00 y en uno de Chile a
    las 12:00. Este test es el que se rompe si alguien quita la conversión.
    """
    a = await _adulto(env, email="madrid@test.com", tz="Europe/Madrid")
    t = await _crear_tarea(env, a["token"])

    # El navegador en Madrid manda UTC: las 18:00 locales de septiembre son las 16:00Z.
    await _colocar(env, a["token"], t["id"], "16:00", 25)

    linea = await _linea(env, a["token"])
    bloque = next(b for b in linea["blocks"] if b["kind"] == "tarea")
    assert bloque["start"] == "18:00:00"
    assert bloque["end"] == "18:25:00"


async def test_la_hora_sale_del_servidor_con_zona_y_no_sin_ella(env):
    """La `planned_start` que vuelve al cliente tiene que decir que es UTC.

    El otro test comprueba que la línea pinte la hora local correcta. Este comprueba lo
    que el navegador recibe, que es otra cosa y se rompe por separado: sin la "Z", un
    `new Date("2026-09-21T13:00:00")` lo lee como las 13:00 **de donde esté el
    cliente**, y el bloque se movería de sitio en cada voyage. Es un fallo que no se ve
    en ningún test de API que no mire la cadena, solo en el JSON.
    """
    a = await _adulto(env, email="zonal@test.com", tz="Europe/Madrid")
    t = await _crear_tarea(env, a["token"])

    await _colocar(env, a["token"], t["id"], "16:00", 25)

    r = await env.client.get("/api/tasks", headers=_cab(a["token"]))
    assert r.status_code == 200, r.text
    fila = next(x for x in r.json() if x["id"] == t["id"])
    # Las 18:00 de Madrid en septiembre son las 16:00 UTC, y eso es lo que se guarda.
    assert fila["planned_start"].endswith("Z") or fila["planned_start"].endswith("+00:00")
    assert fila["planned_start"].startswith("2026-09-21T16:00")


async def test_sin_duracion_respuesta_usa_el_valor_por_defecto(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])

    await _colocar(env, a["token"], t["id"], "17:00")

    linea = await _linea(env, a["token"])
    bloque = next(b for b in linea["blocks"] if b["kind"] == "tarea")
    assert bloque["minutes"] == 30


async def test_mover_una_tarea_ya_colocada_no_pregunta_de_nuevo(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])
    await _colocar(env, a["token"], t["id"], "17:00", 25)

    # Mover sin `minutes` conserva los 25: si los perdiera, un bloque de 30 en la línea
    # que no cuadra con la carga sería el primer síntoma.
    await _colocar(env, a["token"], t["id"], "20:00")

    linea = await _linea(env, a["token"])
    bloque = next(b for b in linea["blocks"] if b["kind"] == "tarea")
    assert bloque["start"] == "20:00:00"
    assert bloque["minutes"] == 25


async def test_quitar_la_colocacion_no_borra_la_tarea(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])
    await _colocar(env, a["token"], t["id"], "17:00", 25)

    r = await env.client.delete(f"/api/tasks/{t['id']}/place", headers=_cab(a["token"]))
    assert r.status_code == 204, r.text

    linea = await _linea(env, a["token"])
    assert not [b for b in linea["blocks"] if b["kind"] == "tarea"]
    assert linea["blocked_minutes"] == 0

    # La tarea sigue viva y pendiente: quitar la hora no es deshacer la tarea.
    tareas = (await env.client.get("/api/tasks", headers=_cab(a["token"]))).json()
    assert [x["title"] for x in tareas] == ["Poner la lavadora"]
    assert tareas[0]["planned_start"] is None


# ---------------------------------------------------------------- el niño


async def test_el_nino_tambien_puede_colocar_un_deber(env):
    a = await _adulto(env)
    token = await _token_de_nino(env, a["token"])
    t = await _crear_tarea(env, token, "Matemáticas", category="colegio-deberes")

    await _colocar(env, token, t["id"], "17:00", 40)

    linea = await _linea(env, token)
    bloque = next(b for b in linea["blocks"] if b["kind"] == "tarea")
    assert bloque["minutes"] == 40


# ---------------------------------------------------------------- permisos


async def test_no_se_puede_colocar_una_tarea_ajena(env):
    a = await _adulto(env)
    otro = await _adulto(env, email="otro@test.com")
    t = await _crear_tarea(env, otro["token"])

    r = await env.client.post(
        f"/api/tasks/{t['id']}/place",
        json={"start": f"{LUNES.isoformat()}T17:00:00+01:00", "minutes": 25},
        headers=_cab(a["token"]),
    )
    assert r.status_code == 404, r.text


async def test_no_se_acepta_una_duracion_que_no_es_un_rato(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])

    r = await env.client.post(
        f"/api/tasks/{t['id']}/place",
        json={"start": f"{LUNES.isoformat()}T17:00:00+01:00", "minutes": 0},
        headers=_cab(a["token"]),
    )
    assert r.status_code == 422, r.text


async def test_una_tarea_hecha_hoy_sigue_ocupando_pero_sale_hecha(env):
    a = await _adulto(env)
    t = await _crear_tarea(env, a["token"])
    await _colocar(env, a["token"], t["id"], "17:00", 25)

    r = await env.client.post(
        f"/api/tasks/{t['id']}/complete",
        json={"done_on": LUNES.isoformat()},
        headers=_cab(a["token"]),
    )
    assert r.status_code == 200, r.text

    linea = await _linea(env, a["token"])
    bloque = next(b for b in linea["blocks"] if b["kind"] == "tarea")
    # El rato se gastó, así que el bloque sigue ahí (borrarlo haría que la línea
    # dejara de contar la tarde) pero marcado como hecho.
    assert bloque["done"] is True
    assert linea["blocked_minutes"] == 25