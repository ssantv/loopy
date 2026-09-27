"""Scheduler de notificaciones (Roadmap paso 9).

Dos mitades:

- **`fill_outbox`**: planifica lo próximo de cada usuario en su zona horaria
  (aviso de tareas con `notify`, check-in del niño, resumen diario del adulto
  respetando `week_mask` y excepciones `skip`/`add`). Idempotente gracias al
  índice parcial `(user_id, ref)` con `status='pending'`: cada usuario/evento
  tiene a lo sumo **una** fila pendiente.
- **`run_poller`**: envía lo vencido con pywebpush en `to_thread`. `404/410`
  borra la suscripción; `429/5xx` reintenta con backoff; sin suscripciones se
  cancela. El push es notificación, nunca fuente de verdad (Planteamiento §7).

Convención de fechas: `due_at`/`next_retry_at`/`sent_at` se guardan y comparan
como **UTC naive** (el adaptador SQLite de SQLAlchemy pierde el tzinfo y un
aware mezclado rompería las comparaciones). La conversión de zona horaria del
usuario ocurre solo al planificar.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import SessionLocal
from app.models.adult import DailySummaryConfig, ShoppingItem, SummaryException
from app.models.notify import NotificationOutbox, PushSubscription
from app.models.school import CheckinConfig
from app.models.task import Task
from app.models.user import User
from app.services import home
from app.services.tones import template as tone_template

logger = logging.getLogger("loopy.notify")

KINDS = ("reminder", "checkin", "summary", "test")


def utcnow_naive() -> datetime:
    """Ahora en UTC sin tzinfo (formato portable con SQLite)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _aware(naive: datetime) -> datetime:
    return naive.replace(tzinfo=UTC)


def tz_of(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


# ---------------------------------------------------------------- planificación

def first_masked_day(on_or_after: date, week_mask: int) -> date | None:
    """Primer día >= `on_or_after` cuyo día de la semana está en `week_mask` (bit 0=lun..6=dom)."""
    d = on_or_after
    for _ in range(366):
        if week_mask & (1 << d.weekday()):
            return d
        d += timedelta(days=1)
    return None


def next_masked_dt(week_mask: int, at_time: time, tz: ZoneInfo, start_after: datetime) -> datetime | None:
    """Siguiente (día, `at_time`) estrictamente después de `start_after` que cae en `week_mask`."""
    d = start_after.date()
    if week_mask & (1 << d.weekday()):
        cand = datetime.combine(d, at_time, tzinfo=tz)
        if cand > start_after:
            return cand
    nxt = first_masked_day(d + timedelta(days=1), week_mask)
    if nxt is None:
        return None
    return datetime.combine(nxt, at_time, tzinfo=tz)


def next_summary_dt(
    week_mask: int, at_time: time, tz: ZoneInfo, start_after: datetime, exceptions: dict[date, str]
) -> datetime | None:
    """Siguiente resumen: día con máscara, salvo `skip`; un día con `add` entra aunque no tenga máscara."""
    d = start_after.date()
    for _ in range(366):
        action = exceptions.get(d)
        if action == "skip":
            d += timedelta(days=1)
            continue
        if (week_mask & (1 << d.weekday())) or action == "add":
            cand = datetime.combine(d, at_time, tzinfo=tz)
            if cand > start_after:
                return cand
        d += timedelta(days=1)
    return None


def next_task_reminder_local(task: Task, now_local: datetime) -> datetime | None:
    """Fecha/hora local de la próxima notificación de la tarea (o None).

    - No recurrente: su `due_on` siempre que sea hoy o futuro y la hora aún no pasó.
    - Recurrente: si la ocurrencia de hoy sigue pendiente se avisa hoy; si no, en
      la `next_occurrence` (el hueco atrasado se ignora: no se re-notifica algo
      que quedó pendiente ayer, como en el plan donde lo pasado solo se lista).
    - Si `due_at` es None no hay aviso (los recordatorios requieren hora).
    """
    if task.due_at is None or not task.notify:
        return None
    today = now_local.date()
    if task.rec_type is None:
        ref_day = task.due_on
    else:
        pend = home.task_pending(task, today)
        ref_day = today if pend == today else home.next_occurrence(task, today)
    if ref_day is None or ref_day < today:
        return None
    # `due_at` se guarda como reloj de pared: si es aware lo pasamos a la zona
    # del usuario; si viene naive (SQLite devuelve sin tz) es ya hora local.
    due = task.due_at
    if due.tzinfo is None:
        due_wall = due.replace(tzinfo=now_local.tzinfo)
    else:
        due_wall = due.astimezone(now_local.tzinfo)
    cand_aware = datetime.combine(ref_day, due_wall.time(), tzinfo=now_local.tzinfo)
    if cand_aware <= now_local:
        return None
    return cand_aware


def summarize_day(tasks: list[Task], shopping: list[ShoppingItem], day: date) -> str:
    """Texto del resumen diario: pendientes de hoy, atrasadas y compra."""
    hoy = [t for t in tasks if home.task_pending(t, day) == day]
    atrasadas = [t for t in tasks if (p := home.task_pending(t, day)) is not None and p < day]
    compra = [s for s in shopping if not s.purchased]
    bits: list[str] = []
    if hoy:
        bits.append(f"{len(hoy)} tareas para hoy")
    if atrasadas:
        bits.append(f"{len(atrasadas)} atrasadas")
    if compra:
        bits.append(f"{len(compra)} en la lista de la compra")
    if not bits:
        return "Nada pendiente: respira, todo al día."
    return " · ".join(bits)


async def _has_pending_ref(db: AsyncSession, user_id: int, ref: str) -> bool:
    row = await db.execute(
        select(NotificationOutbox.id).where(
            NotificationOutbox.user_id == user_id,
            NotificationOutbox.ref == ref,
            NotificationOutbox.status == "pending",
        )
    )
    return row.first() is not None


async def _enqueue(db: AsyncSession, user_id: int, kind: str, due_at: datetime, ref: str, payload: dict) -> bool:
    """Inserta la fila si no hay ya una pendiente con el mismo `ref`. Devuelve si se insertó."""
    if await _has_pending_ref(db, user_id, ref):
        return False
    db.add(
        NotificationOutbox(
            user_id=user_id,
            kind=kind,
            due_at=due_at,
            ref=ref,
            payload=payload,
            status="pending",
            attempts=0,
        )
    )
    return True


async def fill_outbox(db: AsyncSession, now_naive: datetime) -> int:
    """Planifica la próxima notificación de cada usuario con suscripción. Devuelve nº de intentos de alta."""
    now_utc_aware = _aware(now_naive)
    sub_user_ids = set((await db.execute(select(PushSubscription.user_id).distinct())).scalars().all())
    if not sub_user_ids:
        return 0

    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(sub_user_ids)))).scalars().all()}
    added = 0

    # --- avisos de tareas con hora + notify ---
    tasks = (
        await db.execute(
            select(Task)
            .where(Task.user_id.in_(sub_user_ids), Task.notify.is_(True), Task.due_at.is_not(None))
            .options(selectinload(Task.completions))
        )
    ).scalars().all()
    for task in tasks:
        user = users.get(task.user_id)
        if user is None:
            continue
        now_local = now_utc_aware.astimezone(tz_of(user))
        next_remind = next_task_reminder_local(task, now_local)
        if next_remind is None:
            continue
        if await _enqueue(
            db,
            task.user_id,
            "reminder",
            next_remind.astimezone(UTC).replace(tzinfo=None),
            f"task:{task.id}",
            {"title": task.title, "notes": task.notes, "url": "/"},
        ):
            added += 1

    # --- check-in del niño ---
    checkin_rows = (
        await db.execute(
            select(CheckinConfig).where(CheckinConfig.user_id.in_(sub_user_ids), CheckinConfig.enabled.is_(True))
        )
    ).scalars().all()
    for conf in checkin_rows:
        user = users.get(conf.user_id)
        if user is None:
            continue
        now_local = now_utc_aware.astimezone(tz_of(user))
        nxt = next_masked_dt(conf.week_mask, conf.checkin_time, tz_of(user), now_local)
        if nxt is None:
            continue
        if await _enqueue(db, conf.user_id, "checkin", nxt.astimezone(UTC).replace(tzinfo=None), "checkin", {}):
            added += 1

    # --- resumen diario del adulto (máscara + excepciones) ---
    summary_rows = (
        await db.execute(
            select(DailySummaryConfig).where(
                DailySummaryConfig.user_id.in_(sub_user_ids), DailySummaryConfig.enabled.is_(True)
            )
        )
    ).scalars().all()
    for conf in summary_rows:
        user = users.get(conf.user_id)
        if user is None:
            continue
        tz = tz_of(user)
        now_local = now_utc_aware.astimezone(tz)
        start = now_local.date() - timedelta(days=1)
        stop = start + timedelta(days=370)
        exc_rows = (
            await db.execute(
                select(SummaryException).where(
                    SummaryException.user_id == conf.user_id,
                    SummaryException.date >= start,
                    SummaryException.date <= stop,
                )
            )
        ).scalars().all()
        exceptions = {e.date: e.action for e in exc_rows}
        nxt = next_summary_dt(conf.week_mask, conf.summary_time, tz, now_local, exceptions)
        if nxt is None:
            continue
        if await _enqueue(
            db,
            conf.user_id,
            "summary",
            nxt.astimezone(UTC).replace(tzinfo=None),
            "summary",
            {"day": nxt.date().isoformat(), "url": "/"},
        ):
            added += 1

    return added


# ---------------------------------------------------------------- envío (poller)

def build_payload(user: User, kind: str, data: dict) -> dict:
    url = data.get("url", "/")
    if kind == "checkin":
        return {"title": "Check-in", "body": tone_template("checkin", user.notification_tone), "url": url}
    if kind == "summary":
        day = data.get("day")
        text = data.get("text") or ("Resumen del día: " + day + " en Loopy" if day else "Revisa el día en Loopy")
        return {"title": "Resumen del día", "body": text, "url": url}
    if kind == "test":
        return {"title": "Loopy", "body": data.get("text", "¡Notificaciones conectadas!"), "url": url}
    # reminder
    title = data.get("title") or "Recordatorio"
    notes = data.get("notes")
    return {"title": title, "body": notes if notes else title, "url": url}


async def _send_push(sub: PushSubscription, payload: dict) -> None:
    from pywebpush import webpush  # import tardío: depende de cryptography/PEM

    sub_info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
    await asyncio.to_thread(
        webpush,
        sub_info,
        json.dumps(payload),
        vapid_private_key=settings.vapid_private_key,
        vapid_claims={"sub": settings.vapid_subject},
        timeout=10,
        ttl=0,
    )


def _error_code(exc: BaseException) -> int:
    resp = getattr(exc, "response", None)
    return int(getattr(resp, "status_code", 0) or 0)


async def run_poller(db: AsyncSession, now_naive: datetime) -> dict:
    """Envía lo vencido y devuelve contadores por resultado."""
    pending = (
        await db.execute(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == "pending",
                NotificationOutbox.due_at <= now_naive,
                or_(NotificationOutbox.next_retry_at.is_(None), NotificationOutbox.next_retry_at <= now_naive),
            )
            .order_by(NotificationOutbox.due_at)
            .limit(200)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    if not pending:
        return {}

    user_ids = {r.user_id for r in pending}
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()}
    subs_by_user: dict[int, list[PushSubscription]] = {}
    for uid in user_ids:
        subs_by_user[uid] = list(
            (await db.execute(select(PushSubscription).where(PushSubscription.user_id == uid))).scalars().all()
        )

    counts = {"sent": 0, "cancelled": 0, "failed": 0, "retry": 0}

    for row in pending:
        if row.kind not in KINDS:
            row.attempts += 1
            row.status = "failed"
            row.last_error = f"kind desconocido: {row.kind}"
            counts["failed"] += 1
            continue

        user = users.get(row.user_id)
        subs = subs_by_user.get(row.user_id, [])
        if user is None or not subs:
            row.status = "cancelled"
            row.last_error = "sin suscripciones"
            counts["cancelled"] += 1
            continue

        payload = build_payload(user, row.kind, dict(row.payload or {}))
        delivered = False
        retryable = False
        removed: list[PushSubscription] = []
        last_error = ""

        for sub in subs:
            try:
                await _send_push(sub, payload)
                delivered = True
            except BaseException as exc:  # noqa: BLE001 - pywebpush lanza excepciones heterogéneas
                code = _error_code(exc)
                last_error = f"HTTP {code}: {exc.__class__.__name__}"
                if code in (404, 410):
                    removed.append(sub)
                elif code == 429 or code >= 500 or code == 0:
                    retryable = True
                else:
                    retryable = False
                    break  # error permanente no reintentable

        for sub in removed:
            subs_by_user[row.user_id].remove(sub)
            await db.delete(sub)

        if delivered:
            row.status = "sent"
            row.sent_at = now_naive
            row.last_error = None
            counts["sent"] += 1
        elif removed and not subs_by_user.get(row.user_id) and not retryable:
            row.status = "cancelled"
            row.last_error = last_error or "todas las suscripciones inválidas"
            counts["cancelled"] += 1
        elif retryable and row.attempts < settings.push_max_attempts - 1:
            row.attempts += 1
            delay = settings.push_backoff[min(row.attempts - 1, len(settings.push_backoff) - 1)]
            row.next_retry_at = now_naive + timedelta(seconds=delay)
            row.last_error = last_error
            counts["retry"] += 1
        else:
            row.attempts += 1
            row.status = "failed"
            row.last_error = last_error or "enviar falló"
            counts["failed"] += 1

    return counts


# ---------------------------------------------------------------- loop del usuario

async def notify_loop() -> None:
    """Bucle del lifespan: poller + relleno cada `push_poll_seconds`."""
    while True:
        try:
            async with SessionLocal() as db:
                now = utcnow_naive()
                try:
                    await run_poller(db, now)
                    await db.commit()
                except Exception:  # noqa: BLE001
                    await db.rollback()
                    logger.exception("poller")
                try:
                    await fill_outbox(db, now)
                    await db.commit()
                except Exception:  # noqa: BLE001
                    await db.rollback()
                    logger.exception("fill_outbox")
        except Exception:  # noqa: BLE001
            logger.exception("notify_loop")
        await asyncio.sleep(settings.push_poll_seconds)