"""Routers del módulo colegio (niño): exámenes, plan de estudio, study_completions y resumen progresivo."""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Exam, OffDay, StudyCompletion, Subject, Task, TaskCompletion
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.school import (
    CalendarDayOut,
    CalendarExtraOut,
    CalendarOut,
    CalendarPlanOut,
    CalendarTaskOut,
    ExamCreate,
    ExamOut,
    ExamPlanOut,
    ExamUpdate,
    PlanItemOut,
    StudyDoneRequest,
    StudyUndoResponse,
    SubjectSessionRequest,
)
from app.services.engine import as_rules, scheduled_dates_between
from app.services.planner import ExamPlanCfg, StudyTask, plan_progress, plan_span, resumen_complete, spread_daily_load
from app.services.schedule import load_school_calendar

router = APIRouter(prefix="/api", tags=["colegio"])

# Cuántos días antes del rango pedido se genera el plan, para que el reparto de
# carga tenga dónde empujar una sesión sin que se salga del cálculo.
SPREAD_LOOKBACK_DAYS = 90


def _expand_off_days(off_rows: list[OffDay], start: date, end: date) -> set[date]:
    """Días sin cole como fechas sueltas, recortados al rango [start, end].

    El planner trabaja con un `set[date]` (igual que hace con los fines de
    semana), no con rangos: así no tiene que saber nada de "vacaciones", solo
    de "este día no".
    """
    days: set[date] = set()
    for row in off_rows:
        d = max(row.start_on, start)
        last = min(row.end_on, end)
        while d <= last:
            days.add(d)
            d += timedelta(days=1)
    return days


async def _off_dates(db: AsyncSession, user_id: int, start: date, end: date) -> set[date]:
    """Días sin cole de un usuario, ya expandidos, para pasárselos al planner."""
    rows = (
        await db.execute(
            select(OffDay).where(OffDay.user_id == user_id, OffDay.end_on >= start, OffDay.start_on <= end)
        )
    ).scalars().all()
    return _expand_off_days(rows, start, end)


# ---------------------------------------------------------------- helpers

async def _owned_exam(exam_id: int, user: User, db: AsyncSession) -> Exam:
    stmt = select(Exam).where(Exam.id == exam_id, Exam.user_id == user.id)
    exam = (await db.execute(stmt)).scalar_one_or_none()
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Examen no encontrado")
    return exam


async def _owned_subject(subject_id: int, user: User, db: AsyncSession) -> Subject:
    stmt = select(Subject).where(Subject.id == subject_id, Subject.user_id == user.id)
    subject = (await db.execute(stmt)).scalar_one_or_none()
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")
    return subject


def _exam_out(exam: Exam, subject: Subject | None = None) -> ExamOut:
    return ExamOut(
        id=exam.id,
        subject_id=exam.subject_id,
        subject_name=subject.name if subject is not None else None,
        exam_date=exam.exam_date,
        notes=exam.notes,
        prep_minutes_override=exam.prep_minutes_override,
        created_at=exam.created_at,
    )


def _resumen_label(subject: Subject, phase: str, done_pages: int) -> str | None:
    """Etiqueta especial para el resumen progresivo (fase 'resumen')."""
    if phase != "resumen" or subject.resumen_total_pages is None or done_pages <= 0:
        return None
    if done_pages >= subject.resumen_total_pages:
        return None
    return f"remata el resumen (llevas {done_pages} de {subject.resumen_total_pages} hojas)"


# ---------------------------------------------------------------- exams

def _cfg_for(subject: Subject, exam: Exam | None = None) -> ExamPlanCfg:
    """Config del plan de un examen: la de su asignatura, con el override si lo hay.

    Un examen puede necesitar mas (o menos) tiempo que su asignatura, y eso se
    guarda en `Exam.prep_minutes_override`.
    """
    if exam is not None and exam.prep_minutes_override is not None:
        return ExamPlanCfg.from_minutes(
            prep_minutes=exam.prep_minutes_override,
            session_minutes=subject.session_minutes,
            weights=(subject.days_resumen, subject.days_estudio, subject.days_practica, subject.days_repaso),
            include_weekends=subject.include_weekends,
            resumen_total_pages=subject.resumen_total_pages,
        )
    return ExamPlanCfg.as_rule(subject)


@router.post("/exams", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
async def create_exam(
    payload: ExamCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ExamOut:
    await _owned_subject(payload.subject_id, user, db)
    exam = Exam(user_id=user.id, **payload.model_dump())
    db.add(exam)
    await db.commit()
    await db.refresh(exam)
    subject = await _owned_subject(exam.subject_id, user, db)
    return _exam_out(exam, subject)


@router.get("/exams", response_model=list[ExamOut])
async def list_exams(
    subject_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExamOut]:
    stmt = select(Exam).where(Exam.user_id == user.id).order_by(Exam.exam_date)
    if subject_id:
        stmt = stmt.where(Exam.subject_id == subject_id)
    rows = (await db.execute(stmt)).scalars().all()
    subjects = {s.id: s for s in (await db.execute(select(Subject).where(Subject.user_id == user.id))).scalars()}
    return [_exam_out(e, subjects.get(e.subject_id)) for e in rows]


@router.get("/exams/{exam_id}", response_model=ExamOut)
async def get_exam(
    exam_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ExamOut:
    exam = await _owned_exam(exam_id, user, db)
    subject = await _owned_subject(exam.subject_id, user, db)
    return _exam_out(exam, subject)


@router.patch("/exams/{exam_id}", response_model=ExamOut)
async def update_exam(
    exam_id: int, payload: ExamUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ExamOut:
    exam = await _owned_exam(exam_id, user, db)
    # `exclude_unset` deja pasar un null explicito solo para el override: asi se
    # puede volver al tiempo de la asignatura (si no, el filtro lo haria imposible).
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if "prep_minutes_override" in payload.model_dump(exclude_unset=True):
        changes["prep_minutes_override"] = payload.prep_minutes_override
    if "subject_id" in changes:
        await _owned_subject(changes["subject_id"], user, db)
    for k, v in changes.items():
        setattr(exam, k, v)
    await db.commit()
    await db.refresh(exam)
    subject = await _owned_subject(exam.subject_id, user, db)
    return _exam_out(exam, subject)


@router.delete("/exams/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exam(exam_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    exam = await _owned_exam(exam_id, user, db)
    await db.delete(exam)
    await db.commit()


# ---------------------------------------------------------------- plan

@router.get("/exams/{exam_id}/plan", response_model=ExamPlanOut)
async def exam_plan(
    exam_id: int,
    from_date: date | None = Query(default=None, alias="from",
                                    description="Primer día a consultar (por defecto hoy)"),
    to: date | None = Query(default=None, description="Último día a consultar (por defecto D-1)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExamPlanOut:
    exam = await _owned_exam(exam_id, user, db)
    subject = await _owned_subject(exam.subject_id, user, db)
    cfg = _cfg_for(subject, exam)

    start = from_date or datetime.now(UTC).date()
    end = to or (exam.exam_date - timedelta(days=1))

    done = (await db.execute(select(StudyCompletion).where(StudyCompletion.exam_id == exam.id))).scalars().all()
    done_by_date = {d.date: d for d in done}

    # El plan salta los días sin cole. Se cubre de sobra el rango que puede
    # recorrer `plan_span` hacia atrás para no quedarse corto.
    off_days = await _off_dates(
        db, user.id, min(start, exam.exam_date - timedelta(days=400)), end
    )

    prog = plan_progress(
        exam.exam_date,
        cfg,
        done_dates={d.date for d in done if d.status in ("done", "skip")},
        today=start,
        resumen_done_pages=subject.resumen_done_pages,
        off_days=off_days,
    )

    items: list[PlanItemOut] = []
    for item in plan_span(exam.exam_date, cfg, start, end, subject.resumen_done_pages, off_days):
        comp = done_by_date.get(item.date)
        items.append(
            PlanItemOut(
                day=item.date,
                phase=item.phase,
                offset=item.offset,
                status=comp.status if comp else None,
                done_at=comp.done_at if comp else None,
                label=_resumen_label(subject, item.phase, subject.resumen_done_pages),
                minutes=item.minutes,
            )
        )

    total = subject.resumen_total_pages
    omitted = resumen_complete(cfg, subject.resumen_done_pages)
    partial = bool(total is not None and not omitted and subject.resumen_done_pages > 0)

    return ExamPlanOut(
        exam=_exam_out(exam, subject),
        subject={
            "id": subject.id,
            "name": subject.name,
            "color": subject.color,
            "prep_minutes": cfg.prep_minutes,
            "session_minutes": cfg.session_minutes,
        },
        items=items,
        resumen_done_pages=subject.resumen_done_pages,
        resumen_total_pages=total,
        resumen_omitted=omitted,
        resumen_partial=partial,
        progress=prog,
    )


# ---------------------------------------------------------------- study completions

@router.post("/exams/{exam_id}/plan/{plan_date}", response_model=StudyUndoResponse)
async def mark_plan_item(
    exam_id: int,
    plan_date: date,
    payload: StudyDoneRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StudyUndoResponse:
    """Marca un ítem del plan como done o skip (upsert de StudyCompletion)."""
    exam = await _owned_exam(exam_id, user, db)
    subject = await _owned_subject(exam.subject_id, user, db)
    cfg = ExamPlanCfg.as_rule(subject)

    request_date = payload.day if payload and payload.day else plan_date
    item = next(
        (
            i
            for i in plan_span(exam.exam_date, cfg, request_date, request_date, subject.resumen_done_pages)
        ),
        None,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ese día no pertenece al plan de este examen",
        )

    status_ = (payload.status if payload else "done") or "done"
    existing = (
        await db.execute(
            select(StudyCompletion).where(StudyCompletion.exam_id == exam.id, StudyCompletion.date == request_date)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = status_
    else:
        db.add(
            StudyCompletion(
                user_id=user.id,
                exam_id=exam.id,
                subject_id=exam.subject_id,
                date=request_date,
                phase=item.phase,
                status=status_,
            )
        )
    await db.commit()
    return StudyUndoResponse(removed=False)


@router.delete("/exams/{exam_id}/plan/{plan_date}", response_model=StudyUndoResponse)
async def undo_plan_item(
    exam_id: int,
    plan_date: date,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StudyUndoResponse:
    exam = await _owned_exam(exam_id, user, db)
    result = await db.execute(
        delete(StudyCompletion).where(StudyCompletion.exam_id == exam.id, StudyCompletion.date == plan_date)
    )
    await db.commit()
    return StudyUndoResponse(removed=result.rowcount or 0 > 0)


# ---------------------------------------------------------- resumen adelantado

@router.post("/subjects/{subject_id}/resumen/advance", response_model=PlanItemOut)
async def advance_resumen(
    subject_id: int,
    payload: StudyDoneRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlanItemOut:
    """Sesión de resumen adelantado: registra una completion sin examen y
    sube resumen_done_pages (si la asignatura tiene "hojas")."""
    subject = await _owned_subject(subject_id, user, db)
    today = payload.day if payload and payload.day else datetime.now(UTC).date()

    db.add(
        StudyCompletion(
            user_id=user.id,
            exam_id=None,
            subject_id=subject.id,
            date=today,
            phase="resumen",
            status="done",
        )
    )
    if subject.resumen_total_pages is not None:
        subject.resumen_done_pages += 1
    await db.commit()
    return PlanItemOut(day=today, phase="resumen", offset=0, status="done")


@router.delete("/subjects/{subject_id}/resumen/advance/{resumen_date}", response_model=StudyUndoResponse)
async def undo_advance_resumen(
    subject_id: int,
    resumen_date: date,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StudyUndoResponse:
    subject = await _owned_subject(subject_id, user, db)
    comp = (
        await db.execute(
            select(StudyCompletion)
            .where(
                StudyCompletion.exam_id.is_(None),
                StudyCompletion.subject_id == subject.id,
                StudyCompletion.date == resumen_date,
                StudyCompletion.phase == "resumen",
            )
            .order_by(StudyCompletion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    removed = comp is not None
    if comp is not None:
        await db.delete(comp)
        if subject.resumen_total_pages is not None and subject.resumen_done_pages > 0:
            subject.resumen_done_pages -= 1
        await db.commit()
    return StudyUndoResponse(removed=removed)


# ---------------------------------------------------------- sesión adelantada (cualquier fase)

@router.post("/subjects/{subject_id}/sessions", response_model=PlanItemOut)
async def add_subject_session(
    subject_id: int,
    payload: SubjectSessionRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlanItemOut:
    """Registra una sesión de estudio adelantada de cualquier fase en una fecha
    concreta, aunque ese día no toque plan del examen (exam_id queda NULL)."""
    subject = await _owned_subject(subject_id, user, db)
    day = payload.day if payload and payload.day else datetime.now(UTC).date()
    phase = payload.phase if payload else "resumen"

    db.add(
        StudyCompletion(
            user_id=user.id,
            exam_id=None,
            subject_id=subject.id,
            date=day,
            phase=phase,
            status="done",
        )
    )
    if phase == "resumen" and subject.resumen_total_pages is not None:
        subject.resumen_done_pages += 1
    await db.commit()
    return PlanItemOut(day=day, phase=phase, offset=0, status="done")


@router.delete("/subjects/{subject_id}/sessions/{session_date}", response_model=StudyUndoResponse)
async def undo_subject_session(
    subject_id: int,
    session_date: date,
    phase: str | None = Query(default=None, description="Fase; por defecto se borra la última sesión sin examen"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StudyUndoResponse:
    subject = await _owned_subject(subject_id, user, db)
    stmt = select(StudyCompletion).where(
        StudyCompletion.exam_id.is_(None),
        StudyCompletion.subject_id == subject.id,
        StudyCompletion.date == session_date,
    )
    if phase:
        stmt = stmt.where(StudyCompletion.phase == phase)
    stmt = stmt.order_by(StudyCompletion.id.desc()).limit(1)
    comp = (await db.execute(stmt)).scalar_one_or_none()
    removed = comp is not None
    if comp is not None:
        await db.delete(comp)
        if comp.phase == "resumen" and subject.resumen_total_pages is not None and subject.resumen_done_pages > 0:
            subject.resumen_done_pages -= 1
        await db.commit()
    return StudyUndoResponse(removed=removed)


# ---------------------------------------------------------------- calendario

@router.get("/calendar", response_model=CalendarOut)
async def calendar(
    from_date: date = Query(alias="from"),
    to: date = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarOut:
    """Días entre `from` y `to` con sus tareas asignadas y el plan de estudio.

    - Tareas: cada tarea activa se proyecta con `scheduled_dates_between`
      (calendario por recurrencia); las hechas ese día exacto se marcan `done`.
    - Plan: items del plan de los exámenes del usuario en el rango + sesiones
      adelantadas sin examen.
    - Días sin cole: se marcan con `no_school` + `off_label` aunque no haya nada
      más ese día, para que el frontend pueda pintar las vacaciones.
    - Extraescolares: las de cada día, ya resueltas a horas concretas.
    """
    start = min(from_date, to)
    end = max(from_date, to)
    if end - start > timedelta(days=370):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rango demasiado grande")

    cal = await load_school_calendar(db, user.id)

    tasks = (
        await db.execute(
            select(Task).where(Task.user_id == user.id, Task.archived_at.is_(None)).order_by(Task.sort, Task.created_at)
        )
    ).scalars().all()
    done_by_task: dict[int, set[date]] = {}
    if tasks:
        comps = (
            await db.execute(select(TaskCompletion).where(TaskCompletion.task_id.in_([t.id for t in tasks])))
        ).scalars().all()
        for c in comps:
            done_by_task.setdefault(c.task_id, set()).add(c.done_on)

    days: dict[str, CalendarDayOut] = {}
    for t in tasks:
        rules = as_rules(t)
        ocurrences = scheduled_dates_between(rules, start, end)
        if not ocurrences and t.due_on and start <= t.due_on <= end:
            ocurrences = [t.due_on]
        for d in ocurrences:
            days.setdefault(d.isoformat(), CalendarDayOut()).tasks.append(
                CalendarTaskOut(
                    id=t.id,
                    title=t.title,
                    category=t.category,
                    subject_id=t.subject_id,
                    due_on=t.due_on,
                    done=d in done_by_task.get(t.id, set()),
                )
            )

    exams = (
        await db.execute(
            select(Exam).where(Exam.user_id == user.id, Exam.exam_date >= start).order_by(Exam.exam_date)
        )
    ).scalars().all()
    subjects = {s.id: s for s in (await db.execute(select(Subject).where(Subject.user_id == user.id))).scalars()}
    sessions = (
        await db.execute(
            select(StudyCompletion)
            .where(StudyCompletion.user_id == user.id, StudyCompletion.exam_id.is_(None))
            .order_by(StudyCompletion.date)
        )
    ).scalars().all()
    completions = (
        await db.execute(
            select(StudyCompletion).where(
                StudyCompletion.user_id == user.id,
                StudyCompletion.exam_id.is_not(None),
            )
        )
    ).scalars().all()
    completed_by_exam: dict[int, dict[date, StudyCompletion]] = {}
    for c in completions:
        completed_by_exam.setdefault(c.exam_id, {})[c.date] = c

    # Días sin cole del rango, expandidos a fechas sueltas para el planner.
    off_rows = (
        await db.execute(
            select(OffDay).where(OffDay.user_id == user.id, OffDay.end_on >= start, OffDay.start_on <= end)
        )
    ).scalars().all()
    off_days = _expand_off_days(off_rows, start, end)

    study_tasks: list[StudyTask] = []
    exam_meta: dict[int, tuple[Exam, Subject | None, int]] = {}
    for ex in exams:
        subject = subjects.get(ex.subject_id)
        cfg = _cfg_for(subject, ex) if subject is not None else ExamPlanCfg()
        done_pages = subject.resumen_done_pages if subject is not None else 0
        exam_meta[ex.id] = (ex, subject, done_pages)
        # Se genera desde antes de `start` porque el reparto de carga puede
        # empujar una sesión a días anteriores al rango pedido.
        for it in plan_span(
            ex.exam_date,
            cfg,
            start - timedelta(days=SPREAD_LOOKBACK_DAYS),
            end,
            done_pages,
            off_days,
        ):
            study_tasks.append(StudyTask(exam_date=ex.exam_date, subject_id=ex.subject_id, item=it, exam_id=ex.id))

    # Reparto de carga: con varios exámenes, los planes por separado pedirían
    # varias sesiones el mismo día. Lo ya completado se queda anclado a su día
    # (el "hecho" se guardó con esa fecha) y solo se mueve lo pendiente.
    done_tasks: list[StudyTask] = []
    pending_tasks: list[StudyTask] = []
    for t in study_tasks:
        if t.exam_id in completed_by_exam and t.date in completed_by_exam[t.exam_id]:
            done_tasks.append(t)
        else:
            pending_tasks.append(t)
    busy: dict[date, int] = {}
    for t in done_tasks:
        busy[t.date] = busy.get(t.date, 0) + t.minutes
    plan_por_dia, sin_cabida = spread_daily_load(
        pending_tasks,
        daily_max_minutes=user.study_max_minutes,
        is_valid=cal.is_school_day,
        busy=busy,
    )
    for t in done_tasks:
        plan_por_dia.setdefault(t.date, []).append(t)

    for day, day_tasks in plan_por_dia.items():
        if not (start <= day <= end):
            continue
        for t in day_tasks:
            ex, subject, done_pages = exam_meta[t.exam_id]
            comp = completed_by_exam.get(ex.id, {}).get(day)
            days.setdefault(day.isoformat(), CalendarDayOut()).plan.append(
                CalendarPlanOut(
                    exam_id=ex.id,
                    subject_id=ex.subject_id,
                    subject_name=subject.name if subject else None,
                    subject_color=subject.color if subject else None,
                    phase=t.phase,
                    date=day,
                    offset=t.item.offset,
                    status=comp.status if comp else None,
                    done_at=comp.done_at if comp else None,
                    label=_resumen_label(subject, t.phase, done_pages) if subject else None,
                    minutes=t.minutes,
                )
            )

    for s in sessions:
        subject = subjects.get(s.subject_id)
        days.setdefault(s.date.isoformat(), CalendarDayOut()).plan.append(
            CalendarPlanOut(
                exam_id=None,
                subject_id=s.subject_id,
                subject_name=subject.name if subject else None,
                subject_color=subject.color if subject else None,
                phase=s.phase,
                date=s.date,
                offset=0,
                status=s.status,
                done_at=s.done_at,
                label=None,
                session=True,
            )
        )

    # Días sin cole y extraescolares. Solo se añaden al dict los días que
    # aportan algo: la respuesta sigue siendo dispersa (un año vacío sigue
    # siendo `{}`) pero las vacaciones y las extraescolares ya salen, sin que
    # el frontend tenga que descargarse 365 entradas vacías.
    day = start
    while day <= end:
        is_off = cal.is_off_day(day)
        extras_today = cal.extras_on(day)
        if is_off or extras_today:
            entry = days.setdefault(day.isoformat(), CalendarDayOut())
            if is_off:
                entry.no_school = True
                # Con rangos solapados gana el primero que empieza antes: es el
                # más probable que describa el periodo entero.
                entry.off_label = next((o.label for o in off_rows if o.start_on <= day <= o.end_on and o.label), None)
            for extra in extras_today:
                entry.extras.append(
                    CalendarExtraOut(id=extra.id, name=extra.name, start_time=extra.start_time, end_time=extra.end_time)
                )
        day += timedelta(days=1)

    return CalendarOut(
        from_date=start, to=end, days=days, unplaced_study_minutes=sum(t.minutes for t in sin_cabida)
    )