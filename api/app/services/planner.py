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
    - Los días sin cole (`off_days`) no son días válidos: el plan salta las
      vacaciones en lugar de pedir estudio un puente. Es el mismo mecanismo que
      excluir fines de semana, con el mismo parámetro `off_days`.
    - Con varios exámenes a la vez, cada plan por separado puede pedir 3 sesiones
      el mismo día. `spread_daily_load` reparte esa carga para respetar un tope
      diario (`study_max_minutes`), moviendo antes lo que sobra y respetando
      siempre que el repaso-final está pegado al examen.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
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


def is_valid_day(day: date, include_weekends: bool, off_days: Collection[date] | None = None) -> bool:
    """Un día es válido para el plan.

    Se excluye si:
    - no se incluyen fines de semana y es sábado/domingo, o
    - el día está marcado como sin cole (vacaciones, puente).
    """
    if off_days is not None and day in off_days:
        return False
    return include_weekends or day.weekday() < 5


def _valid_offsets(
    exam_date: date, cfg: ExamPlanCfg, off_days: Collection[date] | None = None
) -> dict[date, int]:
    """Offset X para cada día válido en [D-total, D-1], caminando hacia atrás.

    X=1 es el día anterior al examen (D−1, o el último día válido antes de
    D cuando se excluyen fines de semana o cae en días sin cole). Se genera
    solo `total` días.
    """
    total = cfg.days_resumen + cfg.days_estudio + cfg.days_practica + cfg.days_repaso
    offsets: dict[date, int] = {}
    x = 0
    d = exam_date - timedelta(days=1)
    while x < total and d < exam_date:
        if is_valid_day(d, cfg.include_weekends, off_days):
            x += 1
            offsets[d] = x
        d -= timedelta(days=1)
    return offsets


def plan_day(
    exam_date: date,
    cfg: ExamPlanCfg,
    day: date,
    resumen_done_pages: int = 0,
    off_days: Collection[date] | None = None,
) -> PlanItem | None:
    """Fase del plan para un día concreto (None si ese día no toca plan)."""
    if day >= exam_date or not is_valid_day(day, cfg.include_weekends, off_days):
        return None
    x = _valid_offsets(exam_date, cfg, off_days).get(day)
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
    off_days: Collection[date] | None = None,
) -> list[PlanItem]:
    """Todos los ítems del plan entre `start` y `end` (ambos inclusive)."""
    end = end or (exam_date - timedelta(days=1))
    start = start or (end - timedelta(days=365))
    items = []
    d = max(start, exam_date - timedelta(days=400))
    while d <= end:
        item = plan_day(exam_date, cfg, d, resumen_done_pages, off_days)
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
    off_days: Collection[date] | None = None,
) -> dict:
    """Cómo va el plan en minutos y sesiones, para poder decirlo en la interfaz.

    `done_dates` son los días ya completados (o saltados: cuentan como hechos).
    Devuelve totales y lo que queda pendiente **a partir de hoy**, que es lo que
    de verdad le importa a quien lo mira.
    """
    done_dates = done_dates or set()
    today = today or date.today()
    # Plan completo (no solo desde hoy): si no, los días que ya quedaron atrás se
    # contarían como ni hechos ni pendientes.
    items = plan_span(exam_date, cfg, resumen_done_pages=resumen_done_pages, off_days=off_days)

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


# ------------------------------------------------------ reparto de carga diaria


@dataclass(frozen=True)
class StudyTask:
    """Un ítem del plan junto al examen al que pertenece.

    Hace falta el contexto del examen para poder repartir carga entre varios
    planes: un `PlanItem` suelto no sabe de qué examen es ni cuánto le urge.
    `exam_id` está para que quien lo pinte (el calendario) pueda volver al
    examen y sacar su nombre y su color sin tener que adivinarlo por fecha.
    """

    exam_date: date
    subject_id: int
    item: PlanItem
    exam_id: int | None = None

    @property
    def phase(self) -> str:
        return self.item.phase

    @property
    def minutes(self) -> int:
        return self.item.minutes

    @property
    def date(self) -> date:
        return self.item.date


# Orden de urgencia: primero lo que pertenece al examen más próximo; dentro de
# un examen, primero lo que está más cerca del examen (offset mayor = repaso-final).
_URGENCY = {phase: rank for rank, phase in enumerate(("repaso-final", "repaso", "practica", "estudio", "resumen"))}


def spread_daily_load(
    tasks: Iterable[StudyTask],
    *,
    daily_max_minutes: int,
    is_valid: Callable[[date], bool] | None = None,
    max_back_days: int = 60,
    busy: dict[date, int] | None = None,
) -> tuple[dict[date, list[StudyTask]], list[StudyTask]]:
    """Reparte sesiones de estudio para que ningún día pase de `daily_max_minutes`.

    El problema: cada examen se planifica por separado, así que con tres
    exámenes la misma semana salen tres sesiones de 30 min en el mismo día
    (90 min de golpe, que a un niño de 8 años no le sirve de nada). El tope
    diario es lo que evita ese día imposible.

    Cómo lo resuelve, en dos pasos y de forma determinista:

    1. Se colocan primero las tareas **más urgentes**, que se quedan donde
       estaban. Así el repaso-final sigue pegado al examen, que es la fase que
       no se puede mover.
    2. Cada tarea que se pasa del topping se busca **hacia atrás** el primer
       día válido con hueco.

    Se mueve trabajo hacia atrás, nunca hacia adelante: Adelantar estudio que
    toca mañana no es un fallo, retrasarlo sí. Al mover hacia atrás solo
    empeora el día siguiente, que ya está lleno por definición, así que empuja
    la carga hacia el pasado, que es donde hay sitio.

    Si aun así no cabe en `max_back_days` días, la tarea se devuelve en el
    segundo elemento del resultado en vez de desaparecer en silencio: es mejor
    poder decir "esto no cabe" que fingir que el plan está completo.

    `daily_max_minutes <= 0` significa **sin tope**: es el valor que se guarda
    cuando alguien decide no querer un límite, y tratar ese 0 como "cabe 0
    minutos" movería todo el estudio al pasado sin que nadie lo hubiera pedido.

    `busy` son minutos ya comprometidos en cada día que el llamante no quiere
    que se toquen (por ejemplo, sesiones ya completadas, que están ancladas a su
    día porque el "hecho" se guardó con esa fecha). Cuentan como ocupados pero no
    se mueven: si se movieran, el plan dejaría de coincidir con lo que el niño
    ya hizo.
    """
    is_valid = is_valid or (lambda _d: True)
    cap = daily_max_minutes if daily_max_minutes > 0 else None
    pending = sorted(
        tasks,
        key=lambda t: (t.exam_date, -t.item.offset, _URGENCY.get(t.phase, 99)),
    )

    by_day: dict[date, list[StudyTask]] = {}
    used: dict[date, int] = dict(busy or {})
    unplaced: list[StudyTask] = []

    for task in pending:
        target = task.date
        if cap is None or (is_valid(target) and used.get(target, 0) + task.minutes <= cap):
            pass
        else:
            found = _find_slot(
                task.date,
                is_valid=is_valid,
                used=used,
                minutes=task.minutes,
                cap=cap,
                max_back_days=max_back_days,
            )
            if found is None:
                unplaced.append(task)
                continue
            target = found
        by_day.setdefault(target, []).append(task)
        used[target] = used.get(target, 0) + task.minutes

    # Orden estable dentro de cada día: primero lo del examen más próximo.
    for day in by_day:
        by_day[day].sort(key=lambda t: (t.exam_date, -t.item.offset, _URGENCY.get(t.phase, 99)))
    return by_day, unplaced


def _find_slot(
    preferred: date,
    *,
    is_valid: Callable[[date], bool],
    used: dict[date, int],
    minutes: int,
    cap: int | None,
    max_back_days: int,
) -> date | None:
    """Primer día hacia atrás desde `preferred` (excluido) con hueco para `minutes`."""
    d = preferred
    for _ in range(max_back_days):
        d -= timedelta(days=1)
        if is_valid(d) and (cap is None or used.get(d, 0) + minutes <= cap):
            return d
    return None