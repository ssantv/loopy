"""Reparto del plan de estudio entre días, compartido por el calendario y la carga del día.

Vive aquí, y no en el router, porque dos sitios necesitan **la misma** respuesta:
el calendario pinta el plan ya repartido y `day_load` necesita saber qué quedó
fuera del tope. Si cada uno calcularlo por su cuenta, un día acabaría
contradiciéndose a sí mismo según dónde se mire.

La regla es la del Planteamiento §2.4: se ordena por urgencia (examen más
próximo, sesión más pegada al examen, fase más urgente), cada ítem se queda en
su día si cabe bajo el tope diario y, si no, se empuja **hacia atrás**; lo que no
encuentra hueco se devuelve aparte en vez de desaparecer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.school import Exam, OffDay, StudyCompletion, Subject
from app.models.user import User
from app.services.planner import ExamPlanCfg, StudyTask, plan_span, spread_daily_load
from app.services.schedule import load_school_calendar

# Cuántos días antes del rango se genera el plan, para que el reparto de carga
# tenga dónde empujar una sesión sin salirse del cálculo.
LOOKBACK_DAYS = 90


@dataclass
class Spread:
    """Resultado del reparto: qué cae en cada día y qué no encontró sitio."""

    plan_por_dia: dict[date, list[StudyTask]]
    sin_cabida: list[StudyTask]
    subjects: dict[int, Subject]
    exam_meta: dict[int, tuple[Exam, Subject | None, int]]
    completed_by_exam: dict[int, dict[date, StudyCompletion]]


def expand_off_days(off_rows: list[OffDay], start: date, end: date) -> set[date]:
    """Días sin cole como fechas sueltas, recortadas al rango.

    El planner trabaja con un `set[date]` (igual que con los fines de semana), no
    con rangos: así no tiene que saber nada de "vacaciones", solo de "este día no".
    """
    days: set[date] = set()
    for row in off_rows:
        d = max(row.start_on, start)
        last = min(row.end_on, end)
        while d <= last:
            days.add(d)
            d += timedelta(days=1)
    return days


def plan_cfg_for(subject: Subject, exam: Exam | None = None) -> ExamPlanCfg:
    """Config del plan de un examen: la de su asignatura, con su override si lo hay.

    Un examen puede necesitar más (o menos) tiempo que su asignatura, y eso se
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


async def spread_exams(db: AsyncSession, user: User, start: date, end: date) -> Spread:
    """Reparte el plan de todos los exámenes pendientes de `user` en `[start, end]`.

    Se genera desde `start - LOOKBACK_DAYS` porque el reparto puede empujar una
    sesión a días anteriores al rango pedido.
    """
    cal = await load_school_calendar(db, user.id)
    exams = (
        await db.execute(
            select(Exam).where(Exam.user_id == user.id, Exam.exam_date >= start).order_by(Exam.exam_date)
        )
    ).scalars().all()
    subjects = {s.id: s for s in (await db.execute(select(Subject).where(Subject.user_id == user.id))).scalars()}
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

    off_rows = (
        await db.execute(
            select(OffDay).where(OffDay.user_id == user.id, OffDay.end_on >= start, OffDay.start_on <= end)
        )
    ).scalars().all()
    off_days = expand_off_days(off_rows, start, end)

    study_tasks: list[StudyTask] = []
    exam_meta: dict[int, tuple[Exam, Subject | None, int]] = {}
    for ex in exams:
        subject = subjects.get(ex.subject_id)
        cfg = plan_cfg_for(subject, ex) if subject is not None else ExamPlanCfg()
        done_pages = subject.resumen_done_pages if subject is not None else 0
        exam_meta[ex.id] = (ex, subject, done_pages)
        for it in plan_span(
            ex.exam_date,
            cfg,
            start - timedelta(days=LOOKBACK_DAYS),
            end,
            done_pages,
            off_days,
        ):
            study_tasks.append(
                StudyTask(exam_date=ex.exam_date, subject_id=ex.subject_id, item=it, exam_id=ex.id)
            )

    # Lo ya completado se queda anclado a su día (el "hecho" se guardó con esa
    # fecha) y solo se mueve lo pendiente; lo hecho cuenta como ocupado.
    done_ids = {id(t) for t in study_tasks if t.exam_id in completed_by_exam and t.date in completed_by_exam[t.exam_id]}
    done_tasks = [t for t in study_tasks if id(t) in done_ids]
    pending_tasks = [t for t in study_tasks if id(t) not in done_ids]
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

    return Spread(
        plan_por_dia=plan_por_dia,
        sin_cabida=sin_cabida,
        subjects=subjects,
        exam_meta=exam_meta,
        completed_by_exam=completed_by_exam,
    )
