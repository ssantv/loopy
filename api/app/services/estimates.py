"""Corrección de estimaciones a partir de lo que el niño realmente tarda (Roadmap paso 10).

`work_sessions` es lo único que sabe lo que cuesta algo de verdad: cada uso del
temporizador deja el tiempo que se **_planeó** (`planned_seconds`) junto al que
pasó (`actual_seconds`). Hasta ahora nadie leía esa tabla; este módulo la
convierte en una corrección de la estimación que el propio usuario escribió a mano.

Las reglas están elegidas para que el módulo **se calle casi siempre**:

- **Nada de correcciones con pocos datos.** Con menos de `MIN_SAMPLES` sesiones
  cualquier "corrección" sería el reflejo de un día raro.
- **La tarea gana al tipo.** Si una tarea recurrente tiene historial propio, se
  usa ese; si no, se cae al tipo de trabajo (`kind`), que es más grueso pero
  tiene más muestras.
- **Mediana, no media.** Un mal día no debería reescribir el plan de la semana.
- **Umbral de discrepancia.** Si la diferencia es pequeña, no se dice nada: una
  app que corrige por corregir pierde la credibilidad en la primera vez que se
  equivoca.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.school import WorkSession
from app.models.user import User

# Con menos muestras no se corrige nada.
MIN_SAMPLES = 3
# Menos de un minuto significa que no se usó el temporizador (marcar y salir).
MIN_USABLE_SECONDS = 60
# Lo que el temporizador usa cuando nadie dijo cuánto dura.
DEFAULT_MINUTES = 25
# Redondeo de salida: nadie planifica en 37 minutos.
STEP = 5
MIN_SUGGESTED = 5
MAX_SUGGESTED = 240
# Por debajo de estas dos diferencias, el módulo no dice nada.
MIN_DIFF_MINUTES = 5
MIN_DIFF_RATIO = 0.2

# `work_sessions.kind` habla de tipos de trabajo y `Task.category` de matière;
# esta es la traducción que usa el temporizador del frontend (`kindDeCategoria`
# en Home.tsx) y que el backend necesita para agrupar el ritmo real por tarea.
KIND_POR_CATEGORIA = {"colegio-deberes": "homework", "colegio-trabajo": "project"}


def kind_de_categoria(categoria: str) -> str:
    """Tipo de trabajo de `work_sessions` que corresponde a una categoría de tarea."""
    return KIND_POR_CATEGORIA.get(categoria, "task")



@dataclass(frozen=True)
class Estimate:
    """Lo que sabemos del ritmo real de un tipo de trabajo.

    `suggested_minutes is None` significa "no hay nada que corregir": el llamador
    no debe enseñar nada. `based_on` dice de dónde sale el dato (`task`, `kind`)
    para que la interfaz pueda decirlo si quiere.
    """

    suggested_minutes: int | None
    samples: int
    based_on: str
    planned_minutes: int
    actual_minutes: int


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def _redondear(minutos: float) -> int:
    return max(MIN_SUGGESTED, min(MAX_SUGGESTED, round(minutos / STEP) * STEP))


async def _muestras(
    db: AsyncSession, user: User, *, kind: str | None, task_id: int | None, solo_tarea: bool
) -> list[tuple[int, int]]:
    stmt = select(WorkSession.planned_seconds, WorkSession.actual_seconds).where(
        WorkSession.user_id == user.id,
        WorkSession.actual_seconds >= MIN_USABLE_SECONDS,
    )
    if solo_tarea:
        if task_id is None:
            return []
        stmt = stmt.where(WorkSession.task_id == task_id)
    elif kind:
        stmt = stmt.where(WorkSession.kind == kind)
    return [(p, a) for p, a in (await db.execute(stmt)).all()]


async def suggest_estimate(
    db: AsyncSession,
    user: User,
    *,
    kind: str | None = None,
    task_id: int | None = None,
    current_minutes: int | None = None,
) -> Estimate:
    """Sugiere minutos reales para `kind`/`task_id`, o `None` si no hay nada que decir.

    `current_minutes` es lo que hoy dice la estimación (el `est_minutes` de la
    tarea, o el mínimo por defecto si no tiene). Se usa solo para decidir si la
    diferencia merece mención, nunca como referencia de la sugerencia.
    """
    base = ""
    filas = await _muestras(db, user, kind=kind, task_id=task_id, solo_tarea=True)
    if len(filas) >= MIN_SAMPLES:
        base = "task"
    elif kind:
        por_tipo = await _muestras(db, user, kind=kind, task_id=task_id, solo_tarea=False)
        if len(por_tipo) >= MIN_SAMPLES:
            base, filas = "kind", por_tipo
    if not base:
        return Estimate(None, len(filas), "", 0, 0)

    planificado = int(round(_median([p for p, _ in filas]) / 60))
    real = _redondear(_median([a for _, a in filas]) / 60)

    referencia = current_minutes if current_minutes is not None else DEFAULT_MINUTES
    diferencia = abs(real - referencia)
    if diferencia < MIN_DIFF_MINUTES or diferencia < MIN_DIFF_RATIO * referencia:
        return Estimate(None, len(filas), base, planificado, real)
    return Estimate(real, len(filas), base, planificado, real)


async def ritmos_reales(
    db: AsyncSession, user: User, pares: Sequence[tuple[str, int]]
) -> dict[tuple[str, int], int]:
    """Minutos reales de varias `(kind, task_id)` de golpe, o los que falten.

    A diferencia de `suggest_estimate` aquí no hay umbral: no se pregunta "qué le
    decimos al usuario" sino "cuánto cuesta esto de verdad", y un dato bueno
    vale aunque la diferencia con lo planificado sea pequeña. Solo entra lo que
    hay para quedarse: los minutos que diga, se le pueden sumar a una carga.

    Dos consultas (por tarea, y por tipo para las que no llegan a `MIN_SAMPLES`)
    en lugar de dos por tarea.
    """
    if not pares:
        return {}
    pedidos = set(pares)
    task_ids = [tid for _, tid in pares]

    por_tarea: dict[int, list[int]] = {}
    if task_ids:
        filas = (
            await db.execute(
                select(WorkSession.actual_seconds, WorkSession.task_id).where(
                    WorkSession.user_id == user.id,
                    WorkSession.actual_seconds >= MIN_USABLE_SECONDS,
                    WorkSession.task_id.in_(task_ids),
                )
            )
        ).all()
        for seg, tid in filas:
            por_tarea.setdefault(tid, []).append(seg)

    faltan = [par for par in pares if len(por_tarea.get(par[1], [])) < MIN_SAMPLES]
    por_tipo: dict[str, list[int]] = {}
    kinds = {kind for kind, _ in faltan}
    if kinds:
        filas = (
            await db.execute(
                select(WorkSession.actual_seconds, WorkSession.kind).where(
                    WorkSession.user_id == user.id,
                    WorkSession.actual_seconds >= MIN_USABLE_SECONDS,
                    WorkSession.kind.in_(kinds),
                )
            )
        ).all()
        for seg, kind in filas:
            por_tipo.setdefault(kind, []).append(seg)

    salida: dict[tuple[str, int], int] = {}
    for kind, tid in pedidos:
        muestras = por_tarea.get(tid, [])
        if len(muestras) >= MIN_SAMPLES:
            salida[(kind, tid)] = _redondear(_median(muestras) / 60)
            continue
        por_kind = por_tipo.get(kind, [])
        if len(por_kind) >= MIN_SAMPLES:
            salida[(kind, tid)] = _redondear(_median(por_kind) / 60)
    return salida
