"""Routers de extraescolares y sesiones de trabajo (temporizador / pomodoro)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Extracurricular, WorkSession
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.school import (
    ExtracurricularCreate,
    ExtracurricularOut,
    ExtracurricularUpdate,
    WorkSessionCreate,
    WorkSessionOut,
)

router = APIRouter(prefix="/api", tags=["colegio"])


# ---------------------------------------------------------- extraescolares

@router.post("/extracurriculars", response_model=ExtracurricularOut, status_code=status.HTTP_201_CREATED)
async def create_extracurricular(
    payload: ExtracurricularCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ExtracurricularOut:
    item = Extracurricular(user_id=user.id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ExtracurricularOut(**item.__dict__)


@router.get("/extracurriculars", response_model=list[ExtracurricularOut])
async def list_extracurriculars(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[ExtracurricularOut]:
    rows = await db.execute(
        select(Extracurricular)
        .where(Extracurricular.user_id == user.id)
        .order_by(Extracurricular.day_of_week, Extracurricular.start_time)
    )
    return [ExtracurricularOut(**e.__dict__) for e in rows.scalars().all()]


@router.patch("/extracurriculars/{extracurricular_id}", response_model=ExtracurricularOut)
async def update_extracurricular(
    extracurricular_id: int,
    payload: ExtracurricularUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExtracurricularOut:
    item = (
        await db.execute(
            select(Extracurricular).where(Extracurricular.id == extracurricular_id, Extracurricular.user_id == user.id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraescolar no encontrado")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(item, k, v)
    await db.commit()
    await db.refresh(item)
    return ExtracurricularOut(**item.__dict__)


@router.delete("/extracurriculars/{extracurricular_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extracurricular(
    extracurricular_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    item = (
        await db.execute(
            select(Extracurricular).where(Extracurricular.id == extracurricular_id, Extracurricular.user_id == user.id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraescolar no encontrado")
    await db.delete(item)
    await db.commit()


# ---------------------------------------------------------- work sessions

@router.post("/work-sessions", response_model=WorkSessionOut, status_code=status.HTTP_201_CREATED)
async def create_work_session(
    payload: WorkSessionCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> WorkSessionOut:
    session = WorkSession(user_id=user.id, **payload.model_dump())
    if payload.completed_at is None:
        session.completed_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return WorkSessionOut(
        id=session.id,
        kind=session.kind,
        task_id=session.task_id,
        planned_seconds=session.planned_seconds,
        actual_seconds=session.actual_seconds,
        completed_at=session.completed_at,
        created_at=session.created_at,
    )


@router.get("/work-sessions", response_model=list[WorkSessionOut])
async def list_work_sessions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[WorkSessionOut]:
    rows = await db.execute(
        select(WorkSession).where(WorkSession.user_id == user.id).order_by(WorkSession.created_at.desc()).limit(100)
    )
    return [WorkSessionOut(**s.__dict__) for s in rows.scalars().all()]