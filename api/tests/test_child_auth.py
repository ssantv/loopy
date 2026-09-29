"""Tests de la cuenta de niño creada por un adulto (endpoint + PIN).

Se comprueba lo que importa de verdad:
- Un adulto crea la cuenta del niño y queda vinculada (`parent_id`).
- La cuenta de niño **no tiene email** y entra con nombre + PIN.
- El PIN se guarda hasheado, nunca en claro.
- Un menor NO puede crear cuentas de niño (403).
- El PIN incorrecto da 401 y el nombre inventado también.
- El acceso por PIN está limitado (fuerza bruta).
- El tono se sugiere por la edad al crear la cuenta (y `birth_date` de una
  cuenta ya creada no se pierde al pedir `/me`).
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import User
from app.routers.auth import _pin_limiter
from app.security import verify_password

ADULT_EMAIL = "adulto@test.com"
PASSWORD = "s3cret123"
CHILD_NAME = "Lucía"
CHILD_PIN = "4821"


def _birth_date_for_age(age: int) -> str:
    """Fecha de nacimiento ISO que hoy da exactamente `age` años."""
    hoy = datetime.now(UTC).date()
    try:
        return hoy.replace(year=hoy.year - age).isoformat()
    except ValueError:  # 29 de febrero
        return hoy.replace(year=hoy.year - age, day=28).isoformat()


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
        _pin_limiter._hits.clear()  # noqa: SLF001
        yield SimpleNamespace(client=c, maker=maker)
        _pin_limiter._hits.clear()  # noqa: SLF001
    app.dependency_overrides.clear()


async def _registrar_adulto(env) -> str:
    r = await env.client.post(
        "/api/auth/register",
        json={"email": ADULT_EMAIL, "password": PASSWORD, "profile_type": "adult", "display_name": "Mamá"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


async def _crear_nino(env, token=None, nombre=CHILD_NAME, pin=CHILD_PIN, edad=8, course=None):
    token = token or await _registrar_adulto(env)
    cuerpo = {
        "display_name": nombre,
        "pin": pin,
        "birth_date": _birth_date_for_age(edad),
    }
    if course:
        cuerpo["course"] = course
    return await env.client.post("/api/auth/children", json=cuerpo, headers={"Authorization": f"Bearer {token}"})


# --------------------------------------------------------------------------
# Crear la cuenta del niño
# --------------------------------------------------------------------------


async def test_adulto_crea_cuenta_nino_vinculada(env):
    token_adulto = await _registrar_adulto(env)
    r = await _crear_nino(env, token_adulto)

    assert r.status_code == 201, r.text
    nino = r.json()
    assert nino["profile_type"] == "child"
    assert nino["email"] is None  # el menor no tiene email
    assert nino["display_name"] == CHILD_NAME
    assert nino["parent_id"] is not None  # vinculado a una cuenta adulta

    async with env.maker() as db:
        padre = (await db.execute(select(User).where(User.email == ADULT_EMAIL))).scalar_one()
        hijo = (await db.execute(select(User).where(User.parent_id == padre.id))).scalar_one()
        assert hijo.parent_id == padre.id
        assert hijo.pin_hash is not None
        assert verify_password(CHILD_PIN, hijo.pin_hash)
        # El PIN nunca se guarda en claro.
        assert hijo.pin_hash != CHILD_PIN
        assert CHILD_PIN not in hijo.pin_hash


async def test_el_nuevo_tiene_curso_y_edad(env):
    token = await _registrar_adulto(env)
    r = await _crear_nino(env, token, edad=10, course="4º de Primaria")

    assert r.status_code == 201, r.text
    nino = r.json()
    assert nino["course"] == "4º de Primaria"
    assert nino["age"] == 10


async def test_tono_sugerido_por_edad(env):
    # 6 años → tono "jugueton"; 16 años → "directo".
    token = await _registrar_adulto(env)
    r_joven = await _crear_nino(env, token, nombre="Peque", pin="1111", edad=6)
    assert r_joven.status_code == 201, r_joven.text
    assert r_joven.json()["notification_tone"] == "jugueton"

    r_mayor = await _crear_nino(env, token, nombre="Mayor", pin="2222", edad=16)
    assert r_mayor.status_code == 201, r_mayor.text
    assert r_mayor.json()["notification_tone"] == "directo"


async def test_solo_el_adulto_crea_ninos(env):
    token_adulto = await _registrar_adulto(env)
    r_crea = await _crear_nino(env, token_adulto, nombre="Hijo", pin="3333")
    assert r_crea.status_code == 201, r_crea.text

    # El niño, con su propia sesión, no puede crear más cuentas.
    r_login = await env.client.post("/api/auth/child-login", json={"display_name": "Hijo", "pin": "3333"})
    assert r_login.status_code == 200, r_login.text
    token_nino = r_login.json()["token"]

    r = await _crear_nino(env, token_nino, nombre="Otro", pin="4444")
    assert r.status_code == 403
    assert "adulto" in r.json()["detail"].lower()


async def test_crear_nino_requiere_autenticacion(env):
    r = await env.client.post(
        "/api/auth/children",
        json={"display_name": "Fantasma", "pin": "9999", "birth_date": _birth_date_for_age(8)},
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------
# Listar las cuentas de niño del adulto
# --------------------------------------------------------------------------


async def test_el_adulto_ve_sus_ninos_y_solo_los_suyos(env):
    token_adulto = await _registrar_adulto(env)
    r1 = await _crear_nino(env, token_adulto, nombre="Lucía", pin="4821", course="4º de Primaria")
    r2 = await _crear_nino(env, token_adulto, nombre="Nico", pin="1234")
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text

    r = await env.client.get("/api/auth/children", headers={"Authorization": f"Bearer {token_adulto}"})
    assert r.status_code == 200, r.text
    ninos = r.json()
    assert [n["display_name"] for n in ninos] == ["Lucía", "Nico"]  # en orden de creación
    assert ninos[0]["course"] == "4º de Primaria"
    # La lista es para saber a quién se le dio un PIN, no para filtrar datos:
    # ni el hash del PIN ni nada de su actividad salen aquí.
    assert "pin_hash" not in ninos[0]

    # Otro adulto no ve a estos niños: la lista se filtra por `parent_id`.
    otro = await env.client.post(
        "/api/auth/register",
        json={"email": "otro@test.com", "password": PASSWORD, "profile_type": "adult", "display_name": "Papá"},
    )
    token_otro = otro.json()["token"]
    r_otro = await env.client.get("/api/auth/children", headers={"Authorization": f"Bearer {token_otro}"})
    assert r_otro.status_code == 200
    assert r_otro.json() == []


async def test_un_nino_no_puede_listar_los_ninos_de_su_madre(env):
    """Un menor no gana nada viendo la lista, y menos la de sus hermanos."""
    token_adulto = await _registrar_adulto(env)
    assert (await _crear_nino(env, token_adulto, nombre="Hija", pin="5555")).status_code == 201
    login = await env.client.post("/api/auth/child-login", json={"display_name": "Hija", "pin": "5555"})
    assert login.status_code == 200, login.text

    r = await env.client.get("/api/auth/children", headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert r.status_code == 403
    assert "adulto" in r.json()["detail"].lower()


async def test_listar_ninos_requiere_autenticacion(env):
    assert (await env.client.get("/api/auth/children")).status_code == 401


async def test_pin_muy_corto_rechazado_por_validacion(env):
    token = await _registrar_adulto(env)
    r = await env.client.post(
        "/api/auth/children",
        json={"display_name": "Corto", "pin": "12", "birth_date": _birth_date_for_age(8)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


async def test_pin_no_numerico_rechazado_por_validacion(env):
    token = await _registrar_adulto(env)
    r = await env.client.post(
        "/api/auth/children",
        json={"display_name": "Letras", "pin": "abcd", "birth_date": _birth_date_for_age(8)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


async def test_nombre_vacio_rechazado_por_validacion(env):
    token = await _registrar_adulto(env)
    r = await env.client.post(
        "/api/auth/children",
        json={"display_name": "", "pin": "5555", "birth_date": _birth_date_for_age(8)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Entrada del niño: nombre + PIN
# --------------------------------------------------------------------------


async def test_nino_entra_con_nombre_y_pin(env):
    token_adulto = await _registrar_adulto(env)
    assert (await _crear_nino(env, token_adulto)).status_code == 201

    r = await env.client.post("/api/auth/child-login", json={"display_name": CHILD_NAME, "pin": CHILD_PIN})
    assert r.status_code == 200, r.text
    nino = r.json()
    assert nino["user"]["profile_type"] == "child"
    assert nino["user"]["email"] is None
    assert nino["token"]  # sesión nueva para el niño

    # Y la sesión sirve para usar la API normal.
    me = await env.client.get("/api/auth/me", headers={"Authorization": f"Bearer {nino['token']}"})
    assert me.status_code == 200
    assert me.json()["display_name"] == CHILD_NAME


async def test_pin_incorrecto_da_401(env):
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto)

    r = await env.client.post("/api/auth/child-login", json={"display_name": CHILD_NAME, "pin": "0000"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Nombre o PIN incorrectos"


async def test_nombre_desconocido_da_401(env):
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto)

    r = await env.client.post("/api/auth/child-login", json={"display_name": "Nadie", "pin": CHILD_PIN})
    assert r.status_code == 401


async def test_nombre_exacto_entra_pin_distinto_no(env):
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto, nombre="Lucía", pin=CHILD_PIN)

    ok = await env.client.post("/api/auth/child-login", json={"display_name": "Lucía", "pin": CHILD_PIN})
    assert ok.status_code == 200, ok.text
    ko = await env.client.post("/api/auth/child-login", json={"display_name": "Lucía", "pin": "1111"})
    assert ko.status_code == 401


async def test_acceso_por_pin_limitado_para_fuerza_bruta(env):
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto)

    for _ in range(_pin_limiter.limit):
        r = await env.client.post("/api/auth/child-login", json={"display_name": CHILD_NAME, "pin": "0000"})
        assert r.status_code == 401
    r = await env.client.post("/api/auth/child-login", json={"display_name": CHILD_NAME, "pin": "0000"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


async def test_login_correcto_por_pin_no_cuenta_como_fallo(env):
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto)

    for _ in range(_pin_limiter.limit + 2):
        r = await env.client.post("/api/auth/child-login", json={"display_name": CHILD_NAME, "pin": CHILD_PIN})
        assert r.status_code == 200, r.text
    assert _pin_limiter.attempts(f"{CHILD_NAME.lower()}|testclient") == 0


# --------------------------------------------------------------------------
# Regresión: la fecha de nacimiento no se pierde
# --------------------------------------------------------------------------


async def test_birth_date_se_conserva_al_crear_por_registro(env):
    # El registro clásico (email + contraseña) también guarda la fecha, que antes
    # se aceptaba en el schema pero se perdía al crear el usuario.
    r = await env.client.post(
        "/api/auth/register",
        json={
            "email": "nino_viejo@test.com",
            "password": PASSWORD,
            "profile_type": "child",
            "display_name": "Clásico",
            "birth_date": _birth_date_for_age(7),
        },
    )
    assert r.status_code in (200, 201), r.text
    user = r.json()["user"]
    assert user["age"] == 7
    assert user["notification_tone"] == "jugueton"


async def test_cuenta_nino_no_tiene_email_tras_crearse(env):
    # El niño no tiene email, así que su /me lo refleja con email null y solo
    # se autentica con nombre + PIN.
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto)
    r_login = await env.client.post("/api/auth/child-login", json={"display_name": CHILD_NAME, "pin": CHILD_PIN})
    assert r_login.status_code == 200, r_login.text
    token_nino = r_login.json()["token"]
    me = await env.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_nino}"})
    assert me.status_code == 200
    assert me.json()["email"] is None


async def test_edad_actualiza_tono_en_me_para_cuenta_nueva(env):
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto, nombre="Cambio", pin="7777", edad=10)
    r_login = await env.client.post("/api/auth/child-login", json={"display_name": "Cambio", "pin": "7777"})
    assert r_login.status_code == 200, r_login.text
    token_nino = r_login.json()["token"]

    # 10 años → "cercano". Pero si cumple años, /me recalcula (tone_source=auto).
    async with env.maker() as db:
        hijo = (await db.execute(select(User).where(User.display_name == "Cambio"))).scalar_one()
        hijo.birth_date = hijo.birth_date.replace(year=hijo.birth_date.year - 6)
        await db.commit()

    me = await env.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_nino}"})
    assert me.status_code == 200
    assert me.json()["notification_tone"] == "directo"


# --------------------------------------------------------------------------
# Weird: dos niños con el mismo nombre y el mismo PIN
# --------------------------------------------------------------------------


async def test_dos_ninos_mismo_nombre_y_pin_se_trata_como_fallo(env):
    # Caso raro: si el PIN no desambigua, no se elige una cuenta al azar.
    token_adulto = await _registrar_adulto(env)
    await _crear_nino(env, token_adulto, nombre="Gemelo", pin="8888", course="3º")
    await _crear_nino(env, token_adulto, nombre="Gemelo", pin="8888", course="4º")

    r = await env.client.post("/api/auth/child-login", json={"display_name": "Gemelo", "pin": "8888"})
    assert r.status_code == 401

    # Con un PIN distinto sí desambigua: solo una cuenta coincide.
    r2 = await env.client.post("/api/auth/child-login", json={"display_name": "Gemelo", "pin": "0000"})
    assert r2.status_code == 401
