"""Lógica de la vista "Hogar" (adulto): qué toca hoy y qué se puede adelantar.

Sobre el motor de tareas, decide el estado de cada tarea para la página
principal/por habitaciones:

- **pendiente** = ocurrencia <= hoy (también puntuales con `due_on` pasado).
- **adelantada** = siguiente ocurrencia estrictamente > hoy; marcarla desde esta
  vista **la consume** (next = tras hoy) — Planteamiento §2.5.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.engine import REAL_FAMILY, TaskRules, as_rules, is_due_on, pending_occurrence

HOME_CATEGORIES = ("general", "hogar", "puntual")


def task_pending(task, today: date) -> date | None:
    """Ocurrencia pendiente de la tarea (hoy o atrasada), o None si no toca.

    Una tarea **puntual** (sin recurrencia) aparece si `due_on <= hoy` y ese día
    no está ya completado.
    """
    done = {c.done_on for c in task.completions}
    if task.rec_type is None:
        if task.due_on is not None and task.due_on <= today and task.due_on not in done:
            return task.due_on
        return None
    since = (
        task.rec_anchor or task.created_at.date()
        if task.rec_type in ("daily", "weekly_days", "month_day")
        else None
    )
    return pending_occurrence(as_rules(task), today, done, since)


def next_occurrence(task, today: date) -> date | None:
    """Siguiente ocurrencia estrictamente después de hoy (o None).

    - Familia real (`interval`/`rotation_ref`): el cursor `rec_next_due`.
    - Familia calendario: primer día nominal no completo por delante.
    - Puntual: su `due_on` si está en el futuro.
    """
    if task.rec_type is None:
        if task.due_on is not None and task.due_on > today:
            return task.due_on
        return None
    rules: TaskRules = as_rules(task)
    done = {c.done_on for c in task.completions}
    if task.rec_type in REAL_FAMILY:
        cur = task.rec_next_due
        return cur if cur is not None and cur > today else None
    d = today + timedelta(days=1)
    for _ in range(730):
        if is_due_on(rules, d) and d not in done:
            return d
        d += timedelta(days=1)
    return None


def group_home(tasks, rooms, today: date) -> dict:
    """Agrupa las tareas de hogar por habitación (pendientes + adelantadas).

    Devuelve:
    ```
    {
      "rooms":  [{"id", "name", "color", "pending": [...], "ahead": [...]}],
      "no_room": {"pending": [...], "ahead": [...]},
    }
    ```
    Cada ítem es la tarea serializada con `pending` o `next_on` según grupo.
    """
    rooms_out = [
        {"id": r.id, "name": r.name, "color": r.color, "pending": [], "ahead": []}
        for r in rooms
    ]
    room_index = {r.id: i for i, r in enumerate(rooms)}
    no_room: dict[str, list] = {"pending": [], "ahead": []}

    for t in tasks:
        if t.category not in HOME_CATEGORIES:
            continue
        pend = task_pending(t, today)
        nxt = None if pend is not None else next_occurrence(t, today)
        if pend is None and nxt is None:
            continue
        item = _item(t, pending=pend, next_on=nxt)
        if t.room_id is not None and t.room_id in room_index:
            bucket = rooms_out[room_index[t.room_id]]
        else:
            bucket = no_room
        (bucket["pending"] if pend is not None else bucket["ahead"]).append(item)

    return {"rooms": rooms_out, "no_room": no_room}


def _item(task, pending: date | None, next_on: date | None) -> dict:
    return {
        "id": task.id,
        "category": task.category,
        "title": task.title,
        "notes": task.notes,
        "room_id": task.room_id,
        "due_on": task.due_on,
        "due_at": task.due_at,
        "notify": task.notify,
        "rec_type": task.rec_type,
        "est_minutes": task.est_minutes,
        "last_done_on": task.last_done_on,
        "sort": task.sort,
        "created_at": task.created_at,
        "pending": pending,
        "next_on": next_on,
        "done": sorted(c.done_on for c in task.completions),
    }