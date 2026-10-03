"""Routers del check-in diario del niño: config, tono y alta rápida de tareas.

El check-in es exclusivo del perfil niño (Planteamiento §2.4 / §4): hora y
días configurables, tono por edad y alta rápida con 3 tipos (deber / examen /
proyecto) de golpe ("Añadir otro" hasta guardar). El push en sí se programa en
el módulo de notificaciones (outbox + poller); aquí se dejan la config y el
tono listos para consumir.
"""

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CheckinConfig, Exam, HomeworkTemplate, Subject, Task
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.school import (
    CheckinConfigOut,
    CheckinConfigUpdate,
    CheckinToneOut,
    QuickAddDeberOut,
    QuickAddExamenOut,
    QuickAddItem,
    QuickAddProyectoOut,
    QuickAddRequest,
    QuickAddResponse,
)
from app.services.schedule import load_school_calendar
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
    # El guard estaba en `_require_child` pero solo se usaba en el alta rápida: un
    # adulto podía crearse config de check-in y quedarse recibiendo el push de su
    # propio hijo. Con la UI expuesta ya no es un caso teórico.
    _require_child(user)
    return _config_out(await _get_config(user, db))


@router.patch("/config", response_model=CheckinConfigOut)
async def patch_checkin_config(
    payload: CheckinConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckinConfigOut:
    _require_child(user)
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
    """Alta de varios deberes/exámenes/proyectos de golpe.

    Lo importante de aquí es la **fecha límite**: si el niño no la dice (o no la
    dice bien), se deduce del calendario. Sociales los lunes y martes, añadido
    un martes, no es para mañana sino para el siguiente lunes, y si ese lunes
    cae en un puente se salta al siguiente con clase.

    Reglas, por orden de prioridad:
      1. `due_on` explícito en el item: manda, sin tocarlo.
      2. `extracurricular_id`: el próximo día de esa extraescolar.
      3. `subject_id` y la asignatura está en el horario: el próximo día de clase.
      4. Sin origen conocido (un encargo de casa, la rutina): sin fecha límite.
    """
    _require_child(user)
    day = payload.day or datetime.now(UTC).date()
    cal = await load_school_calendar(db, user.id)

    # --- resolver referencias (asignaturas, extraescolares, plantillas) ---
    referenced = {i.subject_id for i in payload.items if i.subject_id is not None}
    subjects: dict[int, Subject] = {}
    if referenced:
        rows = await db.execute(select(Subject).where(Subject.user_id == user.id, Subject.id.in_(referenced)))
        subjects = {s.id: s for s in rows.scalars().all()}
        if referenced - set(subjects):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")

    extra_ids = {i.extracurricular_id for i in payload.items if i.extracurricular_id is not None}
    unknown_extras = {e for e in extra_ids if cal.extracurricular(e) is None}
    if unknown_extras:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraescolar no encontrada")

    tpl_ids = {i.template_id for i in payload.items if i.template_id is not None}
    templates: dict[int, HomeworkTemplate] = {}
    if tpl_ids:
        rows = await db.execute(
            select(HomeworkTemplate).where(HomeworkTemplate.user_id == user.id, HomeworkTemplate.id.in_(tpl_ids))
        )
        templates = {t.id: t for t in rows.scalars().all()}
        if tpl_ids - set(templates):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plantilla no encontrada")
        # Las plantillas traen su propia asignatura: también hay que validarla.
        tpl_subjects = {t.subject_id for t in templates.values() if t.subject_id is not None}
        if tpl_subjects - set(subjects):
            rows = await db.execute(select(Subject).where(Subject.user_id == user.id, Subject.id.in_(tpl_subjects)))
            subjects.update({s.id: s for s in rows.scalars().all()})
            if tpl_subjects - set(subjects):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asignatura no encontrada")

    def resolve_due(
        item: QuickAddItem,
        assigned_on: date,
        subject_id: int | None,
        extracurricular_id: int | None,
    ) -> tuple[date | None, str | None]:
        """Devuelve (fecha límite, de qué regla salió) para un item.

        Se pasan los ids ya resueltos (plantilla incluida) y no `item` a secas:
        con `template_id` la asignatura y el título vienen de la plantilla, y
        la fecha límite tiene que deducirse de esa asignatura, no de la vacía.
        """
        if item.due_on is not None:
            return item.due_on, "manual"
        if extracurricular_id is not None:
            # Si la extraescolar ya no tiene días futuros dentro de su rango de
            # curso, se cae al primer día de cole en vez de inventar una fecha.
            return cal.extracurricular_day(extracurricular_id, assigned_on), "próxima extraescolar"
        if subject_id is not None:
            return cal.next_class_day(subject_id, assigned_on), "próximo día de clase"
        return None, None

    duties: list[tuple[Task, str | None]] = []
    projects: list[tuple[Task, str | None]] = []
    examenes: list[Exam] = []

    for item in payload.items:
        assigned_on = item.assigned_on or day
        tpl = templates.get(item.template_id) if item.template_id is not None else None
        title = item.title or (tpl.title if tpl is not None else None)
        subject_id = item.subject_id if item.subject_id is not None else (tpl.subject_id if tpl else None)
        est_minutes = item.est_minutes if item.est_minutes is not None else (tpl.est_minutes if tpl else None)
        due_on, rule = resolve_due(item, assigned_on, subject_id, item.extracurricular_id)

        if item.type == "deber":
            # Un deber sin plazo sigue siendo un deber: por eso `due_on` puede
            # ser None aquí. Antes se ponía siempre `day`, que mentía: decir
            # "los sociales para hoy" un martes, con clase los lunes y martes,
            # lo convertía en un deber con plazo ese mismo martes.
            deber = Task(
                user_id=user.id,
                category="colegio-deberes",
                title=title,
                subject_id=subject_id,
                extracurricular_id=item.extracurricular_id,
                assigned_on=assigned_on,
                due_on=due_on,
                notes=item.notes,
                est_minutes=est_minutes,
                pending_from_class=item.pending_from_class,
            )
            db.add(deber)
            duties.append((deber, rule))
        elif item.type == "proyecto":
            proyecto = Task(
                user_id=user.id,
                category="colegio-trabajo",
                title=title,
                subject_id=subject_id,
                extracurricular_id=item.extracurricular_id,
                assigned_on=assigned_on,
                due_on=due_on,
                notes=item.notes,
                est_minutes=est_minutes,
            )
            db.add(proyecto)
            projects.append((proyecto, rule))
        else:  # examen
            assert item.subject_id is not None and item.exam_date is not None
            examen = Exam(user_id=user.id, subject_id=item.subject_id, exam_date=item.exam_date, notes=item.notes)
            db.add(examen)
            examenes.append(examen)

    await db.flush()

    def source_of(task: Task) -> tuple[str | None, str | None]:
        """(tipo de origen, nombre) para poder pintarlo sin llamadas extra."""
        if task.extracurricular_id is not None:
            extra = cal.extracurricular(task.extracurricular_id)
            return ("extraescolar", extra.name if extra else None)
        if task.subject_id is not None:
            subject = subjects.get(task.subject_id)
            return ("asignatura", subject.name if subject else None)
        return (None, None)

    def due_out(task: Task, rule: str | None) -> tuple[str | None, str | None]:
        kind, name = source_of(task)
        return (kind, name) if rule else (None, None)

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
                assigned_on=t.assigned_on,
                due_from_rule=rule,
                source_kind=due_out(t, rule)[0],
                source_name=due_out(t, rule)[1],
            )
            for t, rule in duties
        ],
        proyectos=[
            QuickAddProyectoOut(
                id=t.id,
                title=t.title,
                subject_id=t.subject_id,
                due_on=t.due_on,
                est_minutes=t.est_minutes,
                assigned_on=t.assigned_on,
                due_from_rule=rule,
                source_kind=due_out(t, rule)[0],
                source_name=due_out(t, rule)[1],
            )
            for t, rule in projects
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