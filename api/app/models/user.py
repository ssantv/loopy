"""Usuarios y sesiones de token opaco.

Perfil doble: cada cuenta tiene dos perfiles independientes (adulto y niño).
El `profile_type` del usuario es el perfil "jefe" (el que configura la cuenta);
el perfil hijo se crea opcionalmente más adelante.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Perfil que configura la cuenta: adult | child
    profile_type: Mapped[str] = mapped_column(String(8), nullable=False, default="adult")
    display_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Curso del niño ("4º de Primaria"). Solo informativo: se pinta en el perfil.
    course: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Zona horaria del usuario (IANA, p.ej. "Europe/Madrid").
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # Notificaciones: tono y origen (auto según edad, o manual).
    notification_tone: Mapped[str] = mapped_column(String(24), nullable=False, default="cercano")
    tone_source: Mapped[str] = mapped_column(String(8), nullable=False, default="auto")
    birth_date: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    def age(self, on: datetime | None = None) -> int | None:
        """Edad aproximada para elegir tono; None si no hay fecha de nacimiento."""
        if self.birth_date is None:
            return None
        base = on or datetime.now(UTC)
        return base.year - self.birth_date.year - (
            (base.month, base.day) < (self.birth_date.month, self.birth_date.day)
        )


class Session(Base):
    """Sesión con token opaco. El token en sí es hash (sha256) por seguridad."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @classmethod
    def new_token(cls) -> str:
        return secrets.token_urlsafe(settings.session_token_bytes)

    @classmethod
    def hash_token(cls, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def lifetime(cls) -> timedelta:
        return timedelta(days=settings.session_ttl_days)


class PasswordResetToken(Base):
    """Token de un solo uso para restablecer la contraseña vía email.

    Nunca se guarda el token en claro: solo su sha256, como las sesiones. Un
    token queda invalidado cuando se usa (`used_at`) o cuando caduca
    (`expires_at`). Al confirmar un reset se revocan todas las sesiones del
    usuario, por si el robo de la contraseña venía con una sesión viva.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    def new_token(cls) -> str:
        return secrets.token_urlsafe(32)

    @classmethod
    def hash_token(cls, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def lifetime(cls) -> timedelta:
        return timedelta(minutes=settings.password_reset_ttl_minutes)

    def is_usable(self, now: datetime | None = None) -> bool:
        """True si el token aún se puede canjear (no usado y sin caducar)."""
        now = now or datetime.now(UTC)
        expires = self.expires_at
        # SQLite devuelve las fechas sin tzinfo; se asumen UTC para comparar.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return self.used_at is None and expires > now