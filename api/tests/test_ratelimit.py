"""Tests del rate limit del login contra fuerza bruta.

Dos bloques:
- Unitarios de `SlidingWindowLimiter` (ventana deslizante, con reloj inyectable).
- De extremo a extremo contra `POST /api/auth/login` (SQLite en memoria vía
  override de `get_db`, patrón ASGI igual que test_school_endpoints.py).
"""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registra todas las tablas
from app.db import Base, get_db
from app.main import app
from app.routers.auth import _login_limiter
from app.services.ratelimit import SlidingWindowLimiter

EMAIL = "objetivo@test.com"
PASSWORD = "s3cret123"


# --------------------------------------------------------------------------
# Unitarios del limitador (reloj inyectable: sin sleeps)
# --------------------------------------------------------------------------


def test_limita_al_superar_el_maximo():
    lim = SlidingWindowLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        assert lim.retry_after("k", now=0.0) == 0
        lim.record_failure("k", now=1.0)
    assert lim.attempts("k", now=1.0) == 3


def test_bloquea_tras_el_limite_y_calcula_retry_after():
    lim = SlidingWindowLimiter(limit=2, window_seconds=60)
    lim.record_failure("k", now=100.0)
    lim.record_failure("k", now=110.0)
    # Bloqueado: la ventana se libera al caducar el intento más antiguo (100+60).
    assert lim.retry_after("k", now=110.0) == 50
    assert lim.retry_after("k", now=159.0) == 1
    # Ya no bloqueado tras caducar el más antiguo.
    assert lim.retry_after("k", now=161.0) == 0


def test_la_ventana_es_deslizante_no_un_bloque_fijo():
    # Fallo antiguo que caduca: la ventana "se mueve" y el hueco queda libre.
    lim = SlidingWindowLimiter(limit=2, window_seconds=60)
    lim.record_failure("k", now=0.0)
    lim.record_failure("k", now=50.0)
    assert lim.retry_after("k", now=50.0) > 0
    assert lim.attempts("k", now=61.0) == 1  # el de t=0 caducó
    assert lim.retry_after("k", now=61.0) == 0


def test_reset_olvida_los_fallos():
    lim = SlidingWindowLimiter(limit=2, window_seconds=60)
    lim.record_failure("k", now=1.0)
    lim.record_failure("k", now=1.0)
    assert lim.retry_after("k", now=1.0) > 0
    lim.reset("k")
    assert lim.attempts("k", now=1.0) == 0
    assert lim.retry_after("k", now=1.0) == 0


def test_claves_independientes():
    lim = SlidingWindowLimiter(limit=1, window_seconds=60)
    lim.record_failure("a", now=1.0)
    assert lim.retry_after("a", now=1.0) > 0
    assert lim.retry_after("b", now=1.0) == 0


def test_prune_borra_claves_caducadas():
    lim = SlidingWindowLimiter(limit=2, window_seconds=60)
    lim.record_failure("vieja", now=1.0)
    lim.record_failure("nueva", now=500.0)
    lim.prune(now=500.0)
    assert "vieja" not in lim._hits
    assert "nueva" in lim._hits  # noqa: SLF001 - inspección interna aceptada en test


def test_limite_minimo_y_ventana_minima():
    lim = SlidingWindowLimiter(limit=0, window_seconds=0)
    assert lim.limit == 1 and lim.window == 1


# --------------------------------------------------------------------------
# Extremo a extremo: POST /api/auth/login
# --------------------------------------------------------------------------


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
        # El limitador es un singleton de módulo: se limpia entre tests.
        _login_limiter._hits.clear()  # noqa: SLF001
        yield SimpleNamespace(client=c, maker=maker)
        _login_limiter._hits.clear()  # noqa: SLF001
    app.dependency_overrides.clear()
    # Cierra las conexiones del pool antes de que muera el event loop: si no, los
    # hilos de aiosqlite sobreviven y pytest avisa de "Event loop is closed".
    await engine.dispose()


async def _register(env, email=EMAIL, password=PASSWORD):
    r = await env.client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "profile_type": "adult"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


async def _try(env, email=EMAIL, password="malaclave", ip=None):
    headers = {"x-forwarded-for": ip} if ip else None
    return await env.client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers=headers
    )


async def test_login_correcto_no_cuenta_como_fallo(env):
    await _register(env)
    for _ in range(10):  # ni un fallo: nunca debe bloquear
        r = await _try(env, password=PASSWORD)
        assert r.status_code == 200, r.text
    assert _login_limiter.attempts(f"{EMAIL}|testclient") == 0


async def test_bloquea_tras_max_intentos_fallidos(env):
    await _register(env)
    max_attempts = _login_limiter.limit
    for i in range(max_attempts):
        r = await _try(env)
        assert r.status_code == 401, f"intento {i}: {r.text}"
    # El siguiente intento ya ni siquiera comprueba la contraseña: 429.
    r = await _try(env, password=PASSWORD)  # ¡contraseña correcta!
    assert r.status_code == 429
    assert r.json()["detail"].startswith("Demasiados intentos")
    assert int(r.headers["Retry-After"]) > 0


async def test_exito_limpia_el_contador(env):
    await _register(env)
    for _ in range(_login_limiter.limit - 1):
        assert (await _try(env)).status_code == 401
    # Login correcto antes de llegar al límite.
    assert (await env.client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})).status_code == 200
    # El contador se olvidó: siguen entrando más intentos fallidos.
    for _ in range(_login_limiter.limit - 1):
        assert (await _try(env)).status_code == 401
    assert (await env.client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})).status_code == 200


async def test_email_distinto_misma_ip_no_se_bloquea(env):
    await _register(env)
    other = "otro@test.com"
    await _register(env, email=other)
    # Agota los fallos del email objetivo desde la misma IP.
    for _ in range(_login_limiter.limit):
        assert (await _try(env)).status_code == 401
    assert (await _try(env)).status_code == 429  # el objetivo queda bloqueado
    r = await _try(env, email=other, password=PASSWORD)
    assert r.status_code == 200  # el bloqueo es por (email, IP), no por IP sola


async def test_mismo_email_distinta_ip_no_se_bloquea(env):
    await _register(env)
    for _ in range(_login_limiter.limit):
        assert (await _try(env, ip="1.1.1.1")).status_code == 401
    assert (await _try(env, ip="1.1.1.1")).status_code == 429
    # Mismo email desde otra IP: no hereda el bloqueo (el atacante rotando IP queda
    # fuera; se mitiga en el borde con Caddy/nginx, no aquí).
    r = await _try(env, password=PASSWORD, ip="9.9.9.9")
    assert r.status_code == 200


async def test_usa_x_forwarded_for_como_ip(env):
    await _register(env)
    for _ in range(_login_limiter.limit):
        assert (await _try(env, ip="5.5.5.5")).status_code == 401
    r = await _try(env, password=PASSWORD, ip="5.5.5.5")
    assert r.status_code == 429
    # Otra IP (p. ej. el atacante rotando) no hereda el bloqueo.
    assert (await _try(env, password=PASSWORD, ip="6.6.6.6")).status_code == 200


async def test_registro_no_consume_intentos(env):
    await _register(env)
    for _ in range(3):
        await _register(env, email=f"nuevo{_}@test.com")
    assert (await env.client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})).status_code == 200
