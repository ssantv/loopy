"""Timeline del día: qué lo ocupa y cuánto queda libre."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.day import DayBlockOut, DayTimelineOut, HuecoOut
from app.services.clock import hoy
from app.services.day import day_timeline

router = APIRouter(prefix="/api", tags=["dia"])


@router.get("/day-timeline", response_model=DayTimelineOut)
async def get_day_timeline(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    target: date | None = Query(None, alias="date"),
) -> DayTimelineOut:
    """Lo que ocupa el día de `user`, en orden, y el hueco que queda.

    El parámetro se llama `target` para no chocar con el import de
    `datetime.date`, y se expone como `date` en la URL igual que en `day-load`,
    para que las dos se escriban de la misma forma.
    """
    dia = target or hoy(user)
    tl = await day_timeline(db, user, dia)
    return DayTimelineOut(
        date=dia,
        blocks=[
            DayBlockOut(
                kind=b.kind,
                title=b.title,
                start=b.start,
                end=b.end,
                minutes=b.minutes,
                place=b.place,
                affected=list(b.affected),
                cita_id=b.cita_id,
                extra_id=b.extra_id,
                task_id=b.task_id,
                slot=b.slot,
                done=b.done,
            )
            for b in tl.blocks
        ],
        blocked_minutes=tl.blocked_minutes,
        free_minutes=tl.free_minutes,
        huecos=[HuecoOut(start=h.start, end=h.end, minutes=h.minutes) for h in tl.huecos],
    )