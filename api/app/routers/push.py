"""Routers del módulo push: suscripción Web Push y envío de prueba.

Planteamiento §2.1 / §2.5 / §2.7 / §7:
- `GET /api/push/vapid-public-key`: clave pública para `pushManager.subscribe`.
- `POST /api/push/subscribe`: guarda/renueva la suscripción del navegador.
- `DELETE /api/push/subscribe`: la olvida (el navegador ya no está subscrito).
- `GET /api/push/config`: qué necesita la UI para activar el botón.
- `POST /api/push/test`: encola una notificación ahora (vía outbox).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.notify import NotificationOutbox, PushSubscription
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.push import (
    PushConfigOut,
    PushSubscribeOut,
    PushSubscriptionIn,
    PushTestOut,
)
from app.services.notify import utcnow_naive

router = APIRouter(prefix="/api/push", tags=["push"])


@router.get("/vapid-public-key", response_model=PushConfigOut)
async def vapid_public_key() -> PushConfigOut:
    return PushConfigOut(
        enabled=bool(settings.vapid_public_key and settings.vapid_private_key),
        public_key=settings.vapid_public_key,
    )


@router.get("/config", response_model=PushConfigOut)
async def push_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushConfigOut:
    sub = (
        await db.execute(select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1))
    ).scalar_one_or_none()
    return PushConfigOut(
        enabled=bool(settings.vapid_public_key and settings.vapid_private_key),
        public_key=settings.vapid_public_key,
        segment="subscribed" if sub is not None else "none",
    )


@router.post("/subscribe", response_model=PushSubscribeOut, status_code=status.HTTP_201_CREATED)
async def subscribe(
    payload: PushSubscriptionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushSubscribeOut:
    row = (
        await db.execute(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    ).scalar_one_or_none()
    if row is None:
        row = PushSubscription(
            user_id=user.id,
            endpoint=payload.endpoint,
            p256dh=payload.p256dh,
            auth=payload.auth,
            user_agent=payload.user_agent,
        )
        db.add(row)
    else:
        row.user_id = user.id
        row.p256dh = payload.p256dh
        row.auth = payload.auth
        row.user_agent = payload.user_agent
    row.last_seen_at = datetime.now(UTC)
    await db.commit()
    return PushSubscribeOut(subscribed=True)


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    payload: PushSubscriptionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == payload.endpoint, PushSubscription.user_id == user.id
        )
    )
    await db.commit()


@router.post("/test", response_model=PushTestOut)
async def push_test(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushTestOut:
    """Encola una notificación de prueba para este usuario (el poller la envía)."""
    row = NotificationOutbox(
        user_id=user.id,
        kind="test",
        due_at=utcnow_naive(),
        ref=f"test:{uuid4()}",
        payload={"text": "Prueba de notificación: ¡Loopy funciona!", "url": "/"},
        status="pending",
        attempts=0,
    )
    db.add(row)
    await db.commit()
    return PushTestOut(queued=True)