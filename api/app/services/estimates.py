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
