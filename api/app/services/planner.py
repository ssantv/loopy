"""Planner de planes de estudio hacia atrás (módulo colegio).

El plan de un examen es una función pura de la distancia en días válidos
hacia atrás desde el examen: se calcula en tiempo de consulta y NO se
materializa. Solo se persiste lo "hecho" (`StudyCompletion`).

Contrato resuelto (según el ejemplo de Planteamiento §2.4, no la fórmula
literal, que contradice el ejemplo):

    Para un examen el día D y una asignatura (resumen=S, estudio=E,
    práctica=P, repaso=R), sea X la distancia en días válidos hacia atrás
    desde D−1 (X=1 es el día anterior al examen):

        repaso-final: X = 1                     (fijo, no movible, por construcción)
        repaso:       X ∈ [2, R]                (solo si R >= 2)
        práctica:     X ∈ [R+1, R+P]            (solo si P >= 1)
        estudio:      X ∈ [R+P+1, R+P+E]        (solo si E >= 1)
        resumen:      X ∈ [R+P+E+1, R+P+E+S]    (solo si S >= 1)
        fuera del rango -> sin plan

    Ejemplo (S=E=P=R=1), examen el 25/09:

        21/09 | 22/09 | 23/09 | 24/09     | 25/09
        resumen|estudio|práctica|repaso-final| D

    Notas:
    - El último día antes del examen es SIEMPRE repaso-final ("fijo, no
      movible"): X=1 es repaso-final por construcción.
    - Si quedan menos días que el plan completo, las fases se comprimen
      solas hacia atrás: `plan_span` con `start=today` solo entrega los que
      caben.
    - Los fines de semana se incluyen salvo `include_weekends=False`.
    - Resumen adelantado: si `resumen_total_pages` está definido y
      `resumen_done_pages >= resumen_total_pages`, la fase resumen se omite
      del plan. Si está a medias, el ítem de resumen se muestra como
      "remata el resumen (llevas X de Y hojas)".
    - `resumen_total_pages = NULL` -> el resumen no tiene "hojas"; se trata
      como trabajo largo medido por sesiones de estudio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ExamPlanCfg:
    """Parámetros de planificación extraídos de una asignatura."""

    days_resumen: int = 1
    days_estudio: int = 1
    days_practica: int = 1
    days_repaso: int = 1
    include_weekends: bool = True
    resumen_total_pages: int | None = None  # NULL => resumen como trabajo largo

    @classmethod
    def as_rule(cls, obj) -> ExamPlanCfg:
        return cls(
            days_resumen=obj.days_resumen,
            days_estudio=obj.days_estudio,
            days_practica=obj.days_practica,
            days_repaso=obj.days_repaso,
            include_weekends=obj.include_weekends,
            resumen_total_pages=obj.resumen_total_pages,
        )


@dataclass(frozen=True)
class PlanItem:
    """Un día del plan de un examen."""

    date: date
    phase: str  # repaso-final | repaso | practica | estudio | resumen
    offset: int  # X = distancia en días válidos hacia atrás desde D−1


def resumen_complete(cfg: ExamPlanCfg, done_pages: int) -> bool:
    """True si el resumen de la asignatura está terminado y por tanto se omite."""
    return cfg.resumen_total_pages is not None and done_pages >= cfg.resumen_total_pages


def is_valid_day(day: date, include_weekends: bool) -> bool:
    """Un día es válido para el plan (los fines de semana se excluyen si se pide)."""
    return include_weekends or day.weekday() < 5


def _valid_offsets(exam_date: date, cfg: ExamPlanCfg) -> dict[date, int]:
    """Offset X para cada día válido en [D-total, D-1], caminando hacia atrás.

    X=1 es el día anterior al examen (D−1, o el último día válido antes de
    D cuando se excluyen fines de semana). Se genera solo `total` días.
    """
    total = cfg.days_resumen + cfg.days_estudio + cfg.days_practica + cfg.days_repaso
    offsets: dict[date, int] = {}
    x = 0
    d = exam_date - timedelta(days=1)
    while x < total and d < exam_date:
        if is_valid_day(d, cfg.include_weekends):
            x += 1
            offsets[d] = x
        d -= timedelta(days=1)
    return offsets


def plan_day(
    exam_date: date,
    cfg: ExamPlanCfg,
    day: date,
    resumen_done_pages: int = 0,
) -> PlanItem | None:
    """Fase del plan para un día concreto (None si ese día no toca plan)."""
    if day >= exam_date or not is_valid_day(day, cfg.include_weekends):
        return None
    x = _valid_offsets(exam_date, cfg).get(day)
    if x is None:
        return None

    s = cfg.days_resumen if not resumen_complete(cfg, resumen_done_pages) else 0
    e, p, r = cfg.days_estudio, cfg.days_practica, cfg.days_repaso

    if r >= 1 and x == 1:
        phase = "repaso-final"
    elif r >= 1 and x <= r:
        phase = "repaso"
    elif p >= 1 and x <= r + p:
        phase = "practica"
    elif e >= 1 and x <= r + p + e:
        phase = "estudio"
    elif s >= 1 and x <= r + p + e + s:
        phase = "resumen"
    else:
        return None
    return PlanItem(date=day, phase=phase, offset=x)


def plan_span(
    exam_date: date,
    cfg: ExamPlanCfg,
    start: date | None = None,
    end: date | None = None,
    resumen_done_pages: int = 0,
) -> list[PlanItem]:
    """Todos los ítems del plan entre `start` y `end` (ambos inclusive)."""
    end = end or (exam_date - timedelta(days=1))
    start = start or (end - timedelta(days=365))
    items = []
    d = max(start, exam_date - timedelta(days=400))
    while d <= end:
        item = plan_day(exam_date, cfg, d, resumen_done_pages)
        if item is not None:
            items.append(item)
        d += timedelta(days=1)
    return items