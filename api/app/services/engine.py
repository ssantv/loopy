"""Motor de recurrencias.

Dos familias de recurrencia, tal como manda el planteamiento:

- **Calendario** (`daily` | `weekly_days` | `month_day`): el día nominal es fijo.
  La ocurrencia de hoy depende del calendario y de si se completó ese día exacto.
  Marcar por adelantado una ocurrencia futura NO consume la de hoy.
- **Día real** (`interval` | `rotation_ref`): siguiente = fecha real + intervalo.
  Marcar por adelantado SÍ consume (desplaza el cursor).

Regla de visibilidad: la tarea está "pendiente/atrasada" cuando su cursor o su
día nominal pendiente <= hoy.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

# bit 0 = Lunes (isoweekday 1) ... bit 6 = Domingo (isoweekday 7)
WEEKDAY_BIT = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16, 6: 32, 7: 64}

CALENDAR_FAMILY = {"daily", "weekly_days", "month_day"}
REAL_FAMILY = {"interval", "rotation_ref"}


@dataclass(frozen=True)
class TaskRules:
    """Reglas de recurrencia de una tarea (desacopladas del ORM para poder testear)."""

    rec_type: str | None
    rec_interval: int = 1
    rec_unit: str | None = None  # day | week | month
    rec_week_mask: int = 0
    rec_day_of_month: int | None = None  # 0 = último día del mes
    rec_anchor: date | None = None
    rec_next_due: date | None = None


def as_rules(task) -> TaskRules:
    """Extrae reglas de cualquier objeto/colleción con atributos de recurrencia."""
    keys = (
        "rec_type",
        "rec_interval",
        "rec_unit",
        "rec_week_mask",
        "rec_day_of_month",
        "rec_anchor",
        "rec_next_due",
    )
    return TaskRules(**{k: getattr(task, k) for k in keys})


# ---------------------------------------------------------------- primitivas

def _month_occ_date(month: date, day_of_month: int) -> date:
    """Día de aparición en `month` para `rec_day_of_month` (0 = último del mes)."""
    if day_of_month == 0:
        return month + relativedelta(day=31)
    return month + relativedelta(day=day_of_month)


def month_has_day(month: date, day_of_month: int) -> bool:
    return day_of_month in (0,) or day_of_month <= (month + relativedelta(day=31)).day


def _previous_month(first_of_month: date) -> date:
    return first_of_month - relativedelta(months=1)


def add_interval(rules: TaskRules, base: date) -> date:
    """Suma el intervalo real (day/week/month) sobre `base`."""
    n = max(1, rules.rec_interval)
    unit = rules.rec_unit or "day"
    if unit == "day":
        return base + timedelta(days=n)
    if unit == "week":
        return base + timedelta(weeks=n)
    return base + relativedelta(months=n)


def weekday_in_mask(day: date, mask: int) -> bool:
    return bool(mask & (1 << (day.isoweekday() - 1)))


def previous_nominal(rules: TaskRules, d: date) -> date | None:
    """Día nominal inmediatamente anterior a `d` (No incluido)."""
    rt = rules.rec_type
    if rt == "daily":
        return d - timedelta(days=1)
    if rt == "weekly_days":
        for i in range(1, 8):
            c = d - timedelta(days=i)
            if weekday_in_mask(c, rules.rec_week_mask):
                return c
        return None
    if rt == "month_day":
        prev = _previous_month(d - timedelta(days=d.day - 1))
        # saltar meses sin ese día (30/31)
        for _ in range(24):
            if month_has_day(prev, rules.rec_day_of_month or 31):
                return _month_occ_date(prev, rules.rec_day_of_month)
            prev = _previous_month(prev)
        return None
    return None


def next_nominal(rules: TaskRules, d: date) -> date | None:
    """Día nominal inmediatamente después de `d` (No incluido)."""
    rt = rules.rec_type
    if rt == "daily":
        return d + timedelta(days=1)
    if rt == "weekly_days":
        for i in range(1, 8):
            c = d + timedelta(days=i)
            if weekday_in_mask(c, rules.rec_week_mask):
                return c
        return None
    if rt == "month_day":
        nxt = d - timedelta(days=d.day - 1) + relativedelta(months=1)
        for _ in range(24):
            if month_has_day(nxt, rules.rec_day_of_month or 31):
                return _month_occ_date(nxt, rules.rec_day_of_month)
            nxt += relativedelta(months=1)
        return None
    return None


# ------------------------------------------------------------------ pendiente

def pending_occurrence(
    rules: TaskRules, today: date, completed: Collection[date] | None = None, since: date | None = None
) -> date | None:
    """Fecha de la ocurrencia pendiente (hoy o atrasada), o None si no toca.

    - **Familia real** (`interval`/`rotation_ref`): el cursor `rec_next_due`.
      Se queda en la misma fecha hasta completar → "atrasada" persistente (colapsada).
    - **Familia calendario** (`daily`/`weekly_days`/`month_day`): el día nominal
      siempre aparece; una ocurrencia se consume SOLO cuando hay una completion
      con `done_on` = ese día exacto. Marcar por adelantado otra fecha NO la consume.
      `since` (ancla o fecha de creación) limita hacia atrás el barrido de atrasadas.

    `completed` = fechas `done_on` de las completions de la tarea.
    """
    rt = rules.rec_type
    if rt in REAL_FAMILY:
        cursor = rules.rec_next_due
        return cursor if cursor is not None and cursor <= today else None

    if rt in CALENDAR_FAMILY:
        lower = since or rules.rec_anchor
        done = set(completed or ())
        d = today
        walk = 0
        while (lower is None or d >= lower) and walk <= 730:
            if is_due_on(rules, d) and d not in done:
                return d
            d -= timedelta(days=1)
            walk += 1
        return None
    return None


def is_due_on(rules: TaskRules, d: date) -> bool:
    """¿`d` es un día nominal de la tarea (familia calendario)?"""
    rt = rules.rec_type
    if rt == "daily":
        return True
    if rt == "weekly_days":
        return weekday_in_mask(d, rules.rec_week_mask)
    if rt == "month_day":
        dom = rules.rec_day_of_month
        if dom == 0:
            return d.day == (d + relativedelta(day=31)).day  # último día del mes
        return d.day == dom and month_has_day(d, dom)
    return False


def nominal_dates_between(rules: TaskRules, start: date, end: date) -> list[date]:
    """Días nominales (calendario) en el rango [start, end] inclusive."""
    rt = rules.rec_type
    out: list[date] = []
    if rt == "daily":
        d = start
        while d <= end:
            out.append(d)
            d += timedelta(days=1)
    elif rt == "weekly_days":
        d = start
        while d <= end:
            if weekday_in_mask(d, rules.rec_week_mask):
                out.append(d)
            d += timedelta(days=1)
    elif rt == "month_day":
        d = start
        while d <= end:
            if month_has_day(d, rules.rec_day_of_month or 31) and is_due_on(rules, d):
                out.append(d)
            d += timedelta(days=1)
    return out


def scheduled_dates_between(rules: TaskRules, start: date, end: date) -> list[date]:
    """Ocurrencias de cualquier familia en [start, end] para vistas de calendario."""
    if rules.rec_type in CALENDAR_FAMILY:
        return nominal_dates_between(rules, start, end)
    # familia real: desde rec_next_due (o ancla), pasos de intervalo
    out: list[date] = []
    cur = rules.rec_next_due or rules.rec_anchor
    if cur is None:
        return out
    if cur > end:
        return out
    while cur < start and cur is not None:
        cur = add_interval(rules, cur)
        if cur >= start:
            break
    while cur is not None and cur <= end:
        out.append(cur)
        cur = add_interval(rules, cur)
    return out


def compute_next_cursor(rules: TaskRules, from_date: date) -> date:
    """Cursor después de completar la ocurrencia de `from_date`."""
    if rules.rec_type in REAL_FAMILY:
        return add_interval(rules, from_date)
    nxt = next_nominal(rules, from_date)
    return nxt if nxt is not None else from_date