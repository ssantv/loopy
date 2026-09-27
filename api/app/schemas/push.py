"""Esquemas del módulo push (Web Push, Roadmap paso 9)."""

from __future__ import annotations

from pydantic import BaseModel


class PushSubscriptionIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    user_agent: str | None = None


class PushSubscribeOut(BaseModel):
    subscribed: bool = True


class PushConfigOut(BaseModel):
    """Estado del push para la UI: qué puede y qué falta."""
    enabled: bool
    public_key: str
    segment: str | None = None


class PushTestOut(BaseModel):
    queued: bool = True