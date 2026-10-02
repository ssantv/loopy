"""Routers del listado global de pendientes (Roadmap paso 7, ambos perfiles).

- `GET /api/pending` — todas las tareas con ocurrencia pendiente (hoy + atrasadas).
- `POST /api/pending/complete` — marcado masivo en un solo día (tz del usuario).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.tasks import _serialize
from app.schemas.pending import (
    BulkCompleteRequest,
    BulkCompleteResponse,
    BulkError,
    PendingList,
)
from app.schemas.task import TaskOut
from app.services.clock import hoy
from app.services.pending import bulk_complete, pending_items

router = APIRouter(prefix="/api", tags=["pending"])


@router.get("/pending", response_model=PendingList)
async def list_pending(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> PendingList:
    today = hoy(user)
    overdue, todays = await pending_items(db, user, today)
    return PendingList(
        overdue=[TaskOut(**_serialize(t, today)) for t in overdue],
        today=[TaskOut(**_serialize(t, today)) for t in todays],
    )


@router.post("/pending/complete", response_model=BulkCompleteResponse)
async def bulk_complete_endpoint(
    payload: BulkCompleteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkCompleteResponse:
    today = hoy(user)
    completed, errors = await bulk_complete(db, user, payload.task_ids, today)
    return BulkCompleteResponse(
        completed=completed,
        errors=[BulkError(**e) for e in errors],
        done_on=today,
    )