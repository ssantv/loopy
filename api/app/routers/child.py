"""Routers del check-in diario del niño: config, tono y alta rápida de tareas.

El check-in es exclusivo del perfil niño (Planteamiento §2.4 / §4): hora y
días configurables, tono por edad y alta rápida con 3 tipos (deber / examen /
proyecto) de golpe ("Añadir otro" hasta guardar). El push en sí se programa en
el módulo de notificaciones (outbox + poller); aquí se dejan la config y el
tono listos para consumir.
"""

from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CheckinConfig, Exam, Subject, Task
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.school import (
    CheckinConfigOut,
    CheckinConfigUpdate,
    CheckinToneOut,
    QuickAddDeberOut,
    QuickAddExamenOut,
    QuickAddProyectoOut,
    QuickAddRequest,
    QuickAddResponse,
)
from app.services.tones import template as tone_template

router = APIRouter(prefix="/api/checkin", tags=["checkin"])

DEFAULT_CHECKIN_TIME = time(20, 0)
DEFAULT_WEEK_MASK = 127  # todos los días (bit 0 = Lunes)


def _require_child(user: User) -> None:
    if user.profile_type != "child":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El check-in es solo para el perfil niño",
        )


async def _get_config(user: User, db: AsyncSession) -> CheckinConfig:
    conf = (
        await db.execute(select(CheckinConfig).where(CheckinConfig.user_id == user.id))
    ).scalar_one_or_none()
    if conf is None:
        conf = CheckinConfig(user_id=user.id, checkin_time=DEFAULT_CHECKIN_TIME, week_mask=DEFAULT_WEEK_MASK)
        db.add(conf)
        await db.flush()
    return conf


def _config_out(conf: CheckinConfig) -> CheckinConfigOut:
    return CheckinConfigOut(enabled=conf.enabled, time=conf.checkin_time, week_mask=conf.week_mask)


# ---------------------------------------------------------------- config

@router.get("/config", response_model=CheckinConfigOut)
async def get_checkin_config(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CheckinConfigOut:
    return _config_out(await _get_config(user, db))


@router.patch("/config", response_model=CheckinConfigOut)
async def patch_checkin_config(
    payload: CheckinConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckinConfigOut:
    conf = await _get_config(user, db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(conf, key, value)
    await db.flush()
    return _config_out(conf)


# ---------------------------------------------------------------- tono

@router.get("/tone", response_model=CheckinToneOut)
async def checkin_tone(user: User = Depends(get_current_user)) -> CheckinToneOut:
    return CheckinToneOut(
        notification_tone=user.notification_tone,
        template=tone_template("checkin", user.notification_tone),
    )


# ---------------------------------------------------------------- alta rápida

@router.post("/items", response_model=QuickAddResponse, status_code=status.HTTP_201_CREATED)
async def quick_add_items(
    payload: QuickAddRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickAddResponse:
    _require_child(user)
    day = payload.day or datetime.now(UTC).date()

    referenced = {i.subject_id for i in payload.items if i.subject_id is not None}
    subjects: dict[int, Subject] = {}
    if referenced:
        rows = await db.execute(
            select(Subject).where(Subject.user_id == user.id, Subject.id.in_(referenced))
        )
        subjects = {s.id: s for s in rows.scalars().all()}
        missing = referenced - set(subjects)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Asignatura no encontrada",
            )

    deberes: list[Task] = []
    proyectos: list[Task] = []
    examenes: list[Exam] = []

    for item in payload.items:
        if item.type == "deber":
            deber = Task(
                user_id=user.id,
                category="colegio-deberes",
                title=item.title,
                subject_id=item.subject_id,
                due_on=day,
                notes=item.notes,
                est_minutes=item.est_minutes,
                pending_from_class=item.pending_from_class,
            )
            db.add(deber)
            deberes.append(deber)
        elif item.type == "proyecto":
            proyecto = Task(
                user_id=user.id,
                category="colegio-trabajo",
                title=item.title,
                subject_id=item.subject_id,
                due_on=item.due_on,
                notes=item.notes,
                est_minutes=item.est_minutes,
            )
            db.add(proyecto)
            proyectos.append(proyecto)
        else:  # examen
            assert item.subject_id is not None and item.exam_date is not None
            examen = Exam(user_id=user.id, subject_id=item.subject_id, exam_date=item.exam_date, notes=item.notes)
            db.add(examen)
            examenes.append(examen)

    await db.flush()

    return QuickAddResponse(
        day=day,
        deberes=[
            QuickAddDeberOut(
                id=t.id,
                title=t.title,
                subject_id=t.subject_id,
                due_on=t.due_on,
                est_minutes=t.est_minutes,
                pending_from_class=t.pending_from_class,
            )
            for t in deberes
        ],
        proyectos=[
            QuickAddProyectoOut(
                id=t.id,
                title=t.title,
                subject_id=t.subject_id,
                due_on=t.due_on,
                est_minutes=t.est_minutes,
            )
            for t in proyectos
        ],
        examenes=[
            QuickAddExamenOut(
                id=e.id,
                subject_id=e.subject_id,
                subject_name=subjects[e.subject_id].name,
                exam_date=e.exam_date,
                notes=e.notes,
            )
            for e in examenes
        ],
    )