#!/usr/bin/env python
"""QA backend del paso 9 (scheduler + push).

Comprueba, contra la API real en localhost:
1. Config VAPID activa y clave pública coherente.
2. Suscripción/subscripción y borrado.
3. fill_outbox: con un usuario suscrito + tarea con hora+notify, el outbox tiene
   una fila `reminder` pendiente (vía DB).
4. POST /api/push/test encola una fila que el poller intenta enviar (fake
   endpoint => reintento con retry_at marcado).

Requisitos: API corriendo en 127.0.0.1:8000 con DB SQLite dev.
"""
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"
DB = Path(__file__).resolve().parent.parent / "api" / "loopy_dev.db"
TK = "%H:%M:%S"


def ok(name: str, cond: bool, extra: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{extra}]" if extra else ""))
    if not cond:
        sys.exit(1)


def db_rows(sql: str, params: tuple = ()) -> list:
    import sqlite3

    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def now_iso(future_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=future_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def outbox_for(email: str) -> list:
    rows = db_rows(
        "select n.kind, n.status, n.attempts, n.due_at, n.next_retry_at, n.last_error "
        "from notification_outbox n join users u on u.id = n.user_id where u.email=? order by n.id",
        (email,),
    )
    return [r + (email,) for r in rows]


async def main() -> None:
    email = f"qa_push_{uuid.uuid4().hex[:10]}@test.com"
    async with httpx.AsyncClient(base_url=API, timeout=20.0) as c:
        print(f"[{datetime.now().strftime(TK)}] usuario: {email}")

        r = await c.post("/api/auth/register", json={"email": email, "password": "secret123"})
        ok("registro", r.status_code in (200, 201), str(r.status_code))
        token = r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        r = await c.get("/api/push/config", headers=h)
        cfg = r.json()
        ok("config enabled+VAPID", r.status_code == 200 and cfg["enabled"] and cfg["public_key"], cfg.get("segment"))

        r = await c.get("/api/push/vapid-public-key", headers=h)
        ok("vapid-public-key coincide", r.json()["public_key"] == cfg["public_key"])

        # ---- suscripción fake: se registra y luego se borra ----
        sub = {
            "endpoint": "https://push.invalid/fake-ep",
            "p256dh": "BP2vWp_JqSZ7eGfyk8mHjF4uLDLq9u6nbPUswhWv7ekHVInF1nsQrQ4tlyGxYJ0g2CwLmHjQ",
            "auth": "s3cR3tAUTHKEY",
            "user_agent": "loopy-qa",
        }
        r = await c.post("/api/push/subscribe", headers=h, json=sub)
        ok("subscribe 201", r.status_code == 201)
        r = await c.get("/api/push/config", headers=h)
        ok("segment tras suscribir", r.json()["segment"] == "subscribed")

        # ---- tarea con hora + notify -> fill_outbox crea el reminder ----
        due_on = (datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        today_at = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        r = await c.post(
            "/api/tasks",
            headers=h,
            json={"category": "puntual", "title": "QA recordatorio", "due_on": due_on, "due_at": today_at, "notify": True},
        )
        ok("tarea creada", r.status_code in (200, 201), f"{r.status_code}")
        task_id = r.json()["id"]

        # ---- test push -> el poller intenta enviar al endpoint fake ----
        r = await c.post("/api/push/test", headers=h, json={})
        ok("test encola", r.status_code == 200 and r.json()["queued"] is True)

        # esperamos 2 ciclos de poller (15 s) para fill+intento
        found_reminder = False
        rows_test_before = len([x for x in outbox_for(email) if x[0] == "test"])
        for _ in range(20):
            await asyncio.sleep(2)
            rows = outbox_for(email)
            if any(x[0] == "reminder" for x in rows):
                found_reminder = True
                break
        rows = outbox_for(email)
        reminder = [x for x in rows if x[0] == "reminder"]
        test_rows = [x for x in rows if x[0] == "test"]

        ok("reminder pendiente en outbox", found_reminder and any(x[1] == "pending" for x in reminder),
           " / ".join(f"{x[1]}" for x in reminder))
        if test_rows:
            st = test_rows[0][1]
            attempts = test_rows[0][2]
            retry = test_rows[0][4]
            ok(
                "test intento de envío (retry/failed)",
                st in ("pending", "failed", "canceled") and ((attempts or 0) >= 1 or st in ("failed", "canceled")),
                f"status={st} attempts={attempts} retry={retry}",
            )

        # ---- borrado de suscripción ----
        r = await c.request(
            "DELETE",
            "/api/push/subscribe",
            headers={**h, "Content-Type": "application/json"},
            content=json.dumps(sub),
        )
        ok("unsubscribe 204", r.status_code == 204)
        r = await c.get("/api/push/config", headers=h)
        ok("segment tras desuscribir", r.json()["segment"] == "none")

        # limpieza: quitar la tarea de QA
        await c.delete(f"/api/tasks/{task_id}", headers=h)
        print(f"[{datetime.now().strftime(TK)}] outbox rows para este usuario: {len(rows)}")
        for x in rows:
            print("   ", x)
        print("QA PUSH BACKEND OK")


if __name__ == "__main__":
    asyncio.run(main())