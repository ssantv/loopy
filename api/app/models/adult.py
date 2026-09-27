"""Modelos del módulo adulto: compra, resumen diario y excepciones.

Planteamiento §2.5: `shopping_items` (pendientes arriba, compradas como
historial), `daily_summary_configs` (hora + días) y `summary_exceptions`
(salvo excepción puntual: skip o add).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ShoppingItem(Base):
    """Línea de la lista de la compra.

    - `purchased` con `purchased_at` queda como historial (deshacer posible);
      "quitar" solo borra lo que nunca se compró.
    - `source='plan'` (según anota el menú en §2.6) o `manual`.
    """

    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    qty: Mapped[str | None] = mapped_column(String(80), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    purchased: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")  # manual | plan
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DailySummaryConfig(Base):
    """Configuración del resumen diario del adulto (hora + días de la semana).

    Mismo bitmask que tareas y check-in: bit 0 = Lunes .. bit 6 = Domingo.
    """

    __tablename__ = "daily_summary_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Columna 'time' (nombre en pl.antonio): atributo distinto para no chocar con
    # la anotación `Mapped[time]` en el mismo modelo (ver CheckinConfig).
    summary_time: Mapped[time] = mapped_column("time", Time, nullable=False)
    week_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=127)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SummaryException(Base):
    """Excepción puntual al resumen: `skip` (ese día no) o `add` (ese día sí).

    "Salvo excepción puntual": un día concreto que se salta o se añade aunque
    no esté en la máscara semanal.
    """

    __tablename__ = "summary_exceptions"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_summary_exception_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # skip | add
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)