"""Tests del flujo de reset de contraseña (endpoint + modelo + mailer).

Se comprueba lo que importa de verdad:
- No se filtra si un email existe (siempre 202 con el mismo mensaje).
- El token se guarda hasheado, no en claro.
- El token es de un solo uso y caduca.
- Al confirmar, se cambia la contraseña y **se revocan las sesiones** vivas.
- El envío está limitado para no spamear el correo de un tercero.
- El mailer nunca revienta aunque el SMTP falle.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import PasswordResetToken, User
from app.routers.auth import _login_limiter, _reset_limiter
from app.services import mailer
from app.services.mailer import password_reset_body, send_email

EMAIL = "reset@test.com"
PASSWORD = "s3cret123"
NUEVA = "nuevaClave456"

GENERICO = "Si el email existe, te hemos enviado un enlace para restablecer la contraseña."


@pytest.fixture
async def env(monkeypatch):
    maker = await make_session_factory()

    async def _get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Capturamos el enlace enviado en vez de tocar SMTP.
    enviados: list[dict] = []

    async def _fake_send(to: str, subject: str, body: str) -> bool:
        enviados.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("app.routers.auth.send_email", _fake_send)

    app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        _login_limiter._hits.clear()  # noqa: SLF001
        _reset_limiter._hits.clear()  # noqa: SLF001
        yield SimpleNamespace(client=c, maker=maker, enviados=enviados)
        _login_limiter._hits.clear()  # noqa: SLF001
        _reset_limiter._hits.clear()  # noqa: SLF001
    app.dependency_overrides.clear()


def _token_de(env, cuerpo: str) -> str:
    """Saca el token del enlace del correo simulado."""
    assert "/reset-password?token=" in cuerpo, cuerpo
    return cuerpo.split("/reset-password?token=")[1].split()[0].strip()


async def _registrar(env, email=EMAIL, password=PASSWORD) -> str:
    r = await env.client.post(
        "/api/auth/register", json={"email": email, "password": password, "profile_type": "adult"}
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


async def _pedir_reset(env, email=EMAIL):
    return await env.client.post("/api/auth/password-reset/request", json={"email": email})


async def _token_valido(env, email=EMAIL) -> str:
    r = await _pedir_reset(env, email)
    assert r.status_code == 202, r.text
    return _token_de(env, env.enviados[-1]["body"])


# --------------------------------------------------------------------------
# Pedir el reset
# --------------------------------------------------------------------------


async def test_request_siempre_202_mismo_mensaje_exista_o_no(env):
    await _registrar(env)
    r_existe = await _pedir_reset(env)
    r_no_existe = await _pedir_reset(env, "nadie@test.com")

    assert r_existe.status_code == 202 and r_no_existe.status_code == 202
    # Mismo texto: no permite adivinar qué emails existen.
    assert r_existe.json()["detail"] == r_no_existe.json()["detail"] == GENERICO
    # Y al email inexistente no se le envía nada.
    assert [e["to"] for e in env.enviados] == [EMAIL]


async def test_request_crea_token_hasheado_y_no_en_claro(env):
    await _registrar(env)
    token = await _token_valido(env)

    async with env.maker() as db:
        row = (await db.execute(select(PasswordResetToken))).scalar_one()
        assert row.token_hash == PasswordResetToken.hash_token(token)
        assert row.token_hash != token
        assert token not in row.token_hash
        assert row.used_at is None


async def test_pedir_reset_invalida_tokens_anteriores(env):
    await _registrar(env)
    await _token_valido(env)
    segundo = await _token_valido(env)

    async with env.maker() as db:
        rows = (await db.execute(select(PasswordResetToken))).scalars().all()
        vivos = [r for r in rows if r.used_at is None]
        # Solo el último sigue vivo: un email, un enlace válido.
        assert len(vivos) == 1
        assert vivos[0].token_hash == PasswordResetToken.hash_token(segundo)


async def test_request_limitado_para_no_spamear(env):
    await _registrar(env)
    for _ in range(_reset_limiter.limit):
        assert (await _pedir_reset(env)).status_code == 202
    r = await _pedir_reset(env)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    # No se ha enviado ningún correo extra al pasar el límite.
    assert len(env.enviados) == _reset_limiter.limit


async def test_el_correo_lleva_el_enlace_publico(env):
    await _registrar(env)
    await _pedir_reset(env)
    enviado = env.enviados[-1]
    assert enviado["to"] == EMAIL
    assert "/reset-password?token=" in enviado["body"]


# --------------------------------------------------------------------------
# Confirmar el reset
# --------------------------------------------------------------------------


async def test_confirm_cambia_la_contrasena(env):
    await _registrar(env)
    token = await _token_valido(env)

    r = await env.client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": NUEVA}
    )
    assert r.status_code == 200, r.text
    # La nueva contraseña sirve y la vieja ya no.
    assert (await env.client.post("/api/auth/login", json={"email": EMAIL, "password": NUEVA})).status_code == 200
    assert (await env.client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})).status_code == 401


async def test_confirm_revoca_las_sesiones_vivas(env):
    token_sesion = await _registrar(env)
    token = await _token_valido(env)
    auth = {"Authorization": f"Bearer {token_sesion}"}
    # La sesión sigue viva antes del reset.
    assert (await env.client.get("/api/auth/me", headers=auth)).status_code == 200

    await env.client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": NUEVA})

    # Si se filtra la contraseña, la sesión vieja no vale: 401.
    assert (await env.client.get("/api/auth/me", headers=auth)).status_code == 401


async def test_token_es_de_un_solo_uso(env):
    await _registrar(env)
    token = await _token_valido(env)
    cuerpo = {"token": token, "new_password": NUEVA}

    assert (await env.client.post("/api/auth/password-reset/confirm", json=cuerpo)).status_code == 200
    # Reusar el mismo token falla.
    assert (await env.client.post("/api/auth/password-reset/confirm", json=cuerpo)).status_code == 400


async def test_token_caducado_falla(env):
    await _registrar(env)
    token = await _token_valido(env)
    async with env.maker() as db:
        row = (await db.execute(select(PasswordResetToken))).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

    r = await env.client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": NUEVA}
    )
    assert r.status_code == 400
    # La contraseña sigue siendo la de siempre.
    assert (await env.client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})).status_code == 200


async def test_token_inventado_falla_con_el_mismo_mensaje(env):
    await _registrar(env)
    await _token_valido(env)
    r = await env.client.post(
        "/api/auth/password-reset/confirm", json={"token": "x" * 40, "new_password": NUEVA}
    )
    assert r.status_code == 400
    # Mismo texto que un token caducado: no se distingue "no existe" de "caducó".
    assert r.json()["detail"] == "El enlace no es válido o ha caducado. Pide uno nuevo."


async def test_contrasena_corta_rechazada_por_validacion(env):
    await _registrar(env)
    token = await _token_valido(env)
    r = await env.client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "corta"})
    assert r.status_code == 422
    # La validación falla antes de tocar nada: la vieja sigue valiendo.
    assert (await env.client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})).status_code == 200


# --------------------------------------------------------------------------
# Modelo y mailer
# --------------------------------------------------------------------------


async def test_is_usable(env):
    user_id = await _user_id(env)
    ahora = datetime.now(UTC)
    async with env.maker() as db:
        db.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash="a" * 64,
                expires_at=ahora + timedelta(minutes=30),
            )
        )
        await db.commit()
        row = (await db.execute(select(PasswordResetToken))).scalar_one()
        assert row.is_usable(ahora) is True
        assert row.is_usable(ahora + timedelta(hours=1)) is False  # caducado
        row.used_at = ahora
        await db.commit()
        assert row.is_usable(ahora) is False  # ya usado


async def test_is_usable_con_fechas_naive_de_sqlite(env):
    # SQLite devuelve los DATETIME sin tzinfo; is_usable no debe reventar.
    user_id = await _user_id(env)
    naive = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=30)
    async with env.maker() as db:
        db.add(PasswordResetToken(user_id=user_id, token_hash="b" * 64, expires_at=naive))
        await db.commit()
        row = (await db.execute(select(PasswordResetToken))).scalar_one()
        assert row.expires_at.tzinfo is None
        assert row.is_usable() is True


async def test_envio_falla_sin_explotar(monkeypatch):
    monkeypatch.setattr(mailer.settings, "smtp_host", "")
    assert await send_email("a@b.com", "s", "c") is False  # sin SMTP: no revienta


async def test_envio_registra_error_de_smtp_sin_raising(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("SMTP caído")

    monkeypatch.setattr(mailer.settings, "smtp_host", "smtp.invalid")
    monkeypatch.setattr(mailer, "_send_sync", _boom)
    assert await send_email("a@b.com", "s", "c") is False


def test_password_reset_body_incluye_el_enlace():
    subject, body = password_reset_body("https://x/reset-password?token=abc", 30)
    assert "https://x/reset-password?token=abc" in body
    assert "30" in body and "Loopy" in subject


# --------------------------------------------------------------------------
# Auxiliar
# --------------------------------------------------------------------------


async def _user_id(env) -> int:
    await _registrar(env)
    async with env.maker() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one()
        return user.id
