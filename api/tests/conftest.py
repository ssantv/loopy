"""Utilidades compartidas de la suite de tests.

Centraliza la creación de la SQLite en memoria y su cierre. Todos los engines
creados aquí se registran para poder disposerlos al final de cada test: si no,
los hilos de aiosqlite sobreviven al event loop y pytest avisa de
"Event loop is closed", ensuciando la salida y escondiendo avisos reales.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 - registra todas las tablas
from app.db import Base

_engines: list = []


async def make_session_factory() -> async_sessionmaker[AsyncSession]:
    """Crea una SQLite en memoria con el esquema y devuelve su sessionmaker."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _engines.append(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _dispose_test_engines():
    """Cierra al final de cada test los engines registrados en el módulo."""
    yield
    while _engines:
        await _engines.pop().dispose()
