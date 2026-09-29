"""Router de contexto escolar: horario, días sin cole y plantillas de deber.

Tres bloques, todos bajo el mismo prefijo `/api` que el resto del módulo:

- `/timetable`          qué días tiene cada asignatura
- `/off-days`           rangos de vacaciones/puentes
- `/homework-templates` atajos para el alta rápida de deberes

Se agrupan en un router porque los tres son "cómo es mi cole", que es
literalmente lo que se configura una vez desde Perfil. Y comparten el
`SchoolCalendar` de `app.services.schedule`, que es quien decide qué cuenta
como día con clase.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import HomeworkTemplate, OffDay, ScheduleSlot, Subject
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.school import (
    HomeworkTemplateCreate,
    HomeworkTemplateOut,
    HomeworkTemplateUpdate,
    OffDayCreate,
    OffDayOut,
    TimetableOut,
    TimetableSlotCreate,
    TimetableSlotOut,
)

router = APIRouter(prefix="/api", tags=["colegio"])


async def _subject_names(db: AsyncSession, user_id: int) -> dict[int, tuple[str, str | None]]:
    """subject_id -> (nombre, color), para no devolver ids pelados al frontend."""
    rows = await db.execute(select(Subject.id, Subject.name, Subject.color).where(Subject.user_id == user_id))
    return {sid: (name, color) for sid, name, color in rows.all()}


# ------------------------------------------------------------------ timetable


@router.get("/timetable", response_model=TimetableOut)
async def get_timetable(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TimetableOut:
    """Horario agrupado por día de la semana (0 = lunes .. 6 = domingo)."""
    rows = (
        await db.execute(
            select(ScheduleSlot)
            .where(ScheduleSlot.user_id == user.id)
            .order_by(ScheduleSlot.day_of_week, ScheduleSlot.id)
        )
    ).scalars().all()
    names = await _subject_names(db, user.id)

    days: dict[int, list[TimetableSlotOut]] = {}
    for slot in rows:
        name, color = names.get(slot.subject_id, (None, None))
        days.setdefault(slot.day_of_week, []).append(
            TimetableSlotOut(
                id=slot.id,
                subject_id=slot.subject_id,
                subject_name=name,
                subject_color=color,
                day_of_week=slot.day_of_week,
            )
        )
    return TimetableOut(days=days)


@router.post("/timetable", response_model=TimetableSlotOut, status_code=status.HTTP_201_CREATED)
async def add_timetable_slot(
    payload: TimetableSlotCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> TimetableSlotOut:
    """Añade una asignatura a un día. Duplicados en el mismo día se ignoran.

    En vez de un 409, se devuelve el slot que ya existía: el frontend puede
    mandar la rejilla entera sin tener que preguntar antes qué hay guardado.
    """
    subject = (
        await db.execute(select(Subject).where(Subject.id == payload.subject_id, Subject.user_id == user.id))
    ).scalar_one_or_none()
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")

    existing = (
        await db.execute(
            select(ScheduleSlot).where(
                ScheduleSlot.user_id == user.id,
                ScheduleSlot.subject_id == payload.subject_id,
                ScheduleSlot.day_of_week == payload.day_of_week,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return TimetableSlotOut(
            id=existing.id,
            subject_id=existing.subject_id,
            subject_name=subject.name,
            subject_color=subject.color,
            day_of_week=existing.day_of_week,
        )

    slot = ScheduleSlot(user_id=user.id, subject_id=payload.subject_id, day_of_week=payload.day_of_week)
    db.add(slot)
    try:
        await db.commit()
    except IntegrityError:  # carrera: dos POST a la vez con la misma asignatura/día
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Esa asignatura ya está ese día"
        ) from None
    await db.refresh(slot)
    return TimetableSlotOut(
        id=slot.id,
        subject_id=slot.subject_id,
        subject_name=subject.name,
        subject_color=subject.color,
        day_of_week=slot.day_of_week,
    )


@router.delete("/timetable/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_timetable_slot(
    slot_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    slot = (
        await db.execute(select(ScheduleSlot).where(ScheduleSlot.id == slot_id, ScheduleSlot.user_id == user.id))
    ).scalar_one_or_none()
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Franja no encontrada")
    await db.delete(slot)
    await db.commit()


# ------------------------------------------------------------------- off-days


def _off_day_out(row: OffDay) -> OffDayOut:
    return OffDayOut(
        id=row.id,
        start_on=row.start_on,
        end_on=row.end_on,
        label=row.label,
        days_count=(row.end_on - row.start_on).days + 1,
    )


@router.get("/off-days", response_model=list[OffDayOut])
async def list_off_days(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[OffDayOut]:
    rows = (
        await db.execute(select(OffDay).where(OffDay.user_id == user.id).order_by(OffDay.start_on))
    ).scalars().all()
    return [_off_day_out(r) for r in rows]


@router.post("/off-days", response_model=OffDayOut, status_code=status.HTTP_201_CREATED)
async def create_off_day(
    payload: OffDayCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> OffDayOut:
    """Marca vacaciones, un puente o un día suelto sin cole.

    Se solapan rangos a propósito: dos vacaciones que se pisan no son un error,
    y al consultar solo importa la unión de los días.
    """
    row = OffDay(user_id=user.id, start_on=payload.start_on, end_on=payload.end_on, label=payload.label)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _off_day_out(row)


@router.delete("/off-days/{off_day_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_off_day(
    off_day_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    row = (
        await db.execute(select(OffDay).where(OffDay.id == off_day_id, OffDay.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rango no encontrado")
    await db.delete(row)
    await db.commit()


# -------------------------------------------------------- homework templates


def _template_out(row: HomeworkTemplate, names: dict[int, tuple[str, str | None]]) -> HomeworkTemplateOut:
    name = names.get(row.subject_id, (None, None))[0] if row.subject_id else None
    return HomeworkTemplateOut(
        id=row.id,
        title=row.title,
        subject_id=row.subject_id,
        subject_name=name,
        est_minutes=row.est_minutes,
        sort=row.sort,
        created_at=row.created_at,
    )


@router.get("/homework-templates", response_model=list[HomeworkTemplateOut])
async def list_homework_templates(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[HomeworkTemplateOut]:
    rows = (
        await db.execute(
            select(HomeworkTemplate)
            .where(HomeworkTemplate.user_id == user.id)
            .order_by(HomeworkTemplate.sort, HomeworkTemplate.id)
        )
    ).scalars().all()
    names = await _subject_names(db, user.id)
    return [_template_out(r, names) for r in rows]


@router.post("/homework-templates", response_model=HomeworkTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_homework_template(
    payload: HomeworkTemplateCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> HomeworkTemplateOut:
    if payload.subject_id is not None:
        ok = (
            await db.execute(select(Subject.id).where(Subject.id == payload.subject_id, Subject.user_id == user.id))
        ).scalar_one_or_none()
        if ok is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")

    row = HomeworkTemplate(user_id=user.id, **payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _template_out(row, await _subject_names(db, user.id))


@router.patch("/homework-templates/{template_id}", response_model=HomeworkTemplateOut)
async def update_homework_template(
    template_id: int,
    payload: HomeworkTemplateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HomeworkTemplateOut:
    row = (
        await db.execute(
            select(HomeworkTemplate).where(HomeworkTemplate.id == template_id, HomeworkTemplate.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")

    data = payload.model_dump(exclude_unset=True)
    if data.get("subject_id") is not None:
        ok = (
            await db.execute(
                select(Subject.id).where(Subject.id == data["subject_id"], Subject.user_id == user.id)
            )
        ).scalar_one_or_none()
        if ok is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")

    for k, v in data.items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return _template_out(row, await _subject_names(db, user.id))


@router.delete("/homework-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_homework_template(
    template_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    row = (
        await db.execute(
            select(HomeworkTemplate).where(HomeworkTemplate.id == template_id, HomeworkTemplate.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
    await db.delete(row)
    await db.commit()


# ------------------------------------------------------------------ utilidades


@router.get("/off-days/covering/{day}", response_model=OffDayOut | None)
async def off_day_covering(
    day: date, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> OffDayOut | None:
    """¿Qué rango sin cole (si hay alguno) cubre este día?

    Útil para el frontend: al pintar un día suelto permite saber si está de
    vacaciones o si es un martes normal, sin tener que descargarse antes todos
    los rangos.
    """
    row = (
        await db.execute(
            select(OffDay).where(OffDay.user_id == user.id, OffDay.start_on <= day, OffDay.end_on >= day)
        )
    ).scalars().first()
    return _off_day_out(row) if row is not None else None
