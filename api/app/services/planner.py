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
    """Parámetros de planificación ya resueltos a **días por fase**.

    El número que configura quien usa la app son minutos (`Subject.prep_minutes`);
    los días de aquí se derivan con `from_minutes`, que reparte las sesiones entre
    las fases según sus pesos.
    """

    days_resumen: int = 1
    days_estudio: int = 1
    days_practica: int = 1
    days_repaso: int = 1
    include_weekends: bool = True
    resumen_total_pages: int | None = None  # NULL => resumen como trabajo largo
    # Duración de una sesión, para poder hablar en minutos en la interfaz.
    session_minutes: int = 30
    # Minutos totales que justifican este plan (ya con el override del examen aplicado).
    prep_minutes: int = 120

    @property
    def total_days(self) -> int:
        return self.days_resumen + self.days_estudio + self.days_practica + self.days_repaso

    @property
    def total_sessions(self) -> int:
        """Sesiones que salen de los minutos configurados."""
        if self.session_minutes <= 0:
            return self.total_days
        return max(1, -(-self.prep_minutes // self.session_minutes))  # ceil

    @classmethod
    def as_rule(cls, obj) -> ExamPlanCfg:
        return cls.from_minutes(
            prep_minutes=obj.prep_minutes,
            session_minutes=obj.session_minutes,
            weights=(obj.days_resumen, obj.days_estudio, obj.days_practica, obj.days_repaso),
            include_weekends=obj.include_weekends,
            resumen_total_pages=obj.resumen_total_pages,
        )

    @classmethod
    def from_minutes(
        cls,
        *,
        prep_minutes: int,
        session_minutes: int,
        weights: tuple[int, int, int, int] = (1, 1, 1, 1),
        include_weekends: bool = True,
        resumen_total_pages: int | None = None,
    ) -> ExamPlanCfg:
        """Convierte "necesito N minutos" en días por fase.

        - sesiones = ceil(prep_minutes / session_minutes), mínimo 1. Un examen nunca
          se queda sin plan por mucho que el tiempo sea pequeño.
        - Las sesiones se reparten entre las fases según `weights`. Un peso de 0
          descarta la fase (p. ej. "Práctica a 0 si la asignatura no la necesita").
        - El sobrante se reparte por resto mayor, y a igualdad gana la fase más
          temprana, para que el reparto sea determinista.
        """
        prep_minutes = max(0, prep_minutes)
        session_minutes = max(1, session_minutes)
        sessions = max(1, -(-prep_minutes // session_minutes))

        w = [max(0, x) for x in weights]
        total_w = sum(w)
        if total_w == 0:
            # Sin pesos declarados: reparto equitativo.
            w, total_w = [1, 1, 1, 1], 4

        exact = [sessions * x / total_w for x in w]
        base = [int(x) for x in exact]
        rest = sessions - sum(base)
        # Índice de las fases que se llevan el sobrante: mayor resto, y a igualdad la más temprana.
        order = sorted(range(4), key=lambda i: (-(exact[i] - base[i]), i))
        for i in order[:rest]:
            base[i] += 1

        return cls(
            days_resumen=base[0],
            days_estudio=base[1],
            days_practica=base[2],
            days_repaso=base[3],
            include_weekends=include_weekends,
            resumen_total_pages=resumen_total_pages,
            session_minutes=session_minutes,
            prep_minutes=prep_minutes,
        )


@dataclass(frozen=True)
class PlanItem:
    """Un día del plan de un examen (un día = una sesión)."""

    date: date
    phase: str  # repaso-final | repaso | practica | estudio | resumen
    offset: int  # X = distancia en días válidos hacia atrás desde D−1
    minutes: int = 30  # duración de la sesión de ese día


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
    return PlanItem(date=day, phase=phase, offset=x, minutes=cfg.session_minutes)


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


def plan_progress(
    exam_date: date,
    cfg: ExamPlanCfg,
    done_dates: set[date] | None = None,
    today: date | None = None,
    resumen_done_pages: int = 0,
) -> dict:
    """Cómo va el plan en minutos y sesiones, para poder decirlo en la interfaz.

    `done_dates` son los días ya completados (o saltados: cuentan como hechos).
    Devuelve totales y lo que queda pendiente **a partir de hoy**, que es lo que
    de verdad le importa a quien lo mira.
    """
    done_dates = done_dates or set()
    today = today or date.today()
    # Plan completo (no solo desde hoy): si no, los días que ya quedaron atrás se
    # contarían como neither hechos ni pendientes.
    items = plan_span(exam_date, cfg, resumen_done_pages=resumen_done_pages)

    done = [i for i in items if i.date in done_dates]
    pending = [i for i in items if i.date >= today and i.date not in done_dates]

    return {
        "session_minutes": cfg.session_minutes,
        "prep_minutes": cfg.prep_minutes,
        "total_sessions": len(items),
        "total_minutes": sum(i.minutes for i in items),
        "done_sessions": len(done),
        "pending_sessions": len(pending),
        "pending_minutes": sum(i.minutes for i in pending),
    }