#!/usr/bin/env python
"""QA backend del paso 7 (Pendientes masivo).

Comprueba, contra la API real en localhost:
1. GET /api/pending agrupa atrasadas vs hoy (puntuales, calendario, intervalo) y
   no filtra tareas de otro usuario.
2. POST /api/pending/complete con varias: las puntuales y calendario se consumen
   con su ocurrencia exacta (atrasada colapsada se limpia), el intervalo se
   recalcula desde HOY.
3. Errores: tarea ajena, lista vacía (422).
4. Estado final en BD (completions y rec_next_due).

Requisitos: API corriendo en 127.0.0.1:8000 con DB SQLite dev.
"""
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"
DB = Path(__file__).resolve().parent.parent / "api" / "loopy_dev.db"

# La consola de Windows va en cp1252 y no sabe imprimir las flechas "→" de los
# mensajes: sin esto el guion revienta al informar, no al fallar.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


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


def last_monday(d: date) -> date:
    return d - timedelta(days=(d.isoweekday() - 1))


async def main() -> None:
    today = datetime.now(timezone.utc).date()  # tz Madrid ≈ UTC+2 (suficiente para fechas ±5 días)
    yesterday = today - timedelta(days=1)
    mon = last_monday(today - timedelta(days=7))  # ancla: un lunes seguro anterior
    expected_c_occ = last_monday(today)  # el lunes de ESTA semana (ya pasado) es la ocurrencia atrasada
    if expected_c_occ == today:
        expected_c_occ -= timedelta(days=7)  # si hoy es lunes, el pendiente es el de la semana pasada

    email = f"qa_pend_{uuid.uuid4().hex[:10]}@test.com"
    email_other = f"qa_pend_other_{uuid.uuid4().hex[:10]}@test.com"
    password = "secret123"

    async with httpx.AsyncClient(base_url=API, timeout=10) as c:
        reg = (await c.post("/api/auth/register", json={"email": email, "password": password})).json()
        h = {"Authorization": f"Bearer {reg['token']}"}
        reg2 = (await c.post("/api/auth/register", json={"email": email_other, "password": password})).json()
        h2 = {"Authorization": f"Bearer {reg2['token']}"}

        # ---- crear tareas ----
        async def mk(payload, headers=h):
            r = await c.post("/api/tasks", json=payload, headers=headers)
            return r

        # A: puntual atrasada (ayer)
        A = (await mk({"category": "puntual", "title": "puntual atrasada", "due_on": str(yesterday)})).json()["id"]
        # B: puntual de hoy
        B = (await mk({"category": "puntual", "title": "puntual hoy", "due_on": str(today)})).json()["id"]
        # C: calendario semanal (lunes) con el lunes pasado sin completar → atrasada colapsada
        C = (
            await mk(
                {
                    "category": "hogar",
                    "title": "polvo",
                    "rec_type": "weekly_days",
                    "rec_week_mask": 1,
                    "rec_anchor": str(expected_c_occ),
                }
            )
        ).json()["id"]
        # D: calendario diario anclado hoy → pendiente hoy
        D = (
            await mk(
                {"category": "hogar", "title": "tender ropa", "rec_type": "daily", "rec_anchor": str(today)}
            )
        ).json()["id"]
        # E: intervalo atrasado (hace 5 días)
        E = (
            await mk(
                {
                    "category": "general",
                    "title": "riego",
                    "rec_type": "interval",
                    "rec_interval": 2,
                    "rec_unit": "day",
                    "rec_next_due": str(today - timedelta(days=5)),
                }
            )
        ).json()["id"]
        # tarea de OTRO usuario, pendiente hoy → no debe salir en el listado
        O = (await mk({"category": "puntual", "title": "ajena", "due_on": str(today)}, headers=h2)).json()["id"]

        pend = (await c.get("/api/pending", headers=h)).json()
        overdue_ids = {t["id"] for t in pend["overdue"]}
        today_ids = {t["id"] for t in pend["today"]}
        ok("GET /api/pending 200 con grupos", A in overdue_ids and C in overdue_ids and E in overdue_ids, f"overdue={sorted(overdue_ids)}")
        ok("puntual y diario de hoy en 'today'", B in today_ids and D in today_ids, f"today={sorted(today_ids)}")
        ok("tarea ajena NO aparece", O not in overdue_ids and O not in today_ids)

        # ---- marcado masivo: puntual atrasada + puntual hoy ----
        res = (await c.post("/api/pending/complete", json={"task_ids": [A, B]}, headers=h)).json()
        ok(
            "complete [A,B] consume ambas",
            sorted(res["completed"]) == sorted([A, B]) and res["errors"] == [] and res["done_on"] == str(today),
            f"completed={res['completed']}",
        )
        pend2 = (await c.get("/api/pending", headers=h)).json()
        ok(
            "A y B dejan de aparecer",
            A not in {t["id"] for g in pend2.values() for t in g}
            and B not in {t["id"] for g in pend2.values() for t in g},
        )

        # ---- calendario atrasado se consume con SU fecha (el lunes pasado) ----
        res = (await c.post("/api/pending/complete", json={"task_ids": [C]}, headers=h)).json()
        ok("complete [C] (semanal atrasada)", res["completed"] == [C] and res["errors"] == [], str(res))
        crow = db_rows("select done_on, rec_next_due from task_completions tc join tasks t on t.id=tc.task_id where t.id=? order by t.id", (C,))
        ok(
            "C consumida con la ocurrencia mostrada (no hoy)",
            crow and crow[0][0] == str(expected_c_occ),
            f"done_on={crow[0][0] if crow else None} esperado={expected_c_occ}",
        )
        ok("C siguiente = el lunes siguiente", crow and crow[0][1] == str(expected_c_occ + timedelta(days=7)), f"next={crow[0][1] if crow else None}")
        pend3 = (await c.get("/api/pending", headers=h)).json()
        ok(
            "C fuera del listado",
            C not in {t["id"] for g in pend3.values() for t in g},
            f"queda D={D in {t['id'] for g in pend3.values() for t in g}} (diario hoy) y E",
        )

        # ---- intervalo se recalcula DESDE HOY ----
        res = (await c.post("/api/pending/complete", json={"task_ids": [E]}, headers=h)).json()
        ok("complete [E] (intervalo)", res["completed"] == [E] and res["errors"] == [], str(res))
        erow = db_rows("select rec_next_due from tasks where id=?", (E,))
        ok("E se recalcula desde HOY (hoy+2)", erow and erow[0][0] == str(today + timedelta(days=2)), f"next={erow[0][0] if erow else None}")
        pend4 = (await c.get("/api/pending", headers=h)).json()
        ok(
            "E fuera del listado; solo queda D (diario hoy)",
            E not in {t["id"] for g in pend4.values() for t in g}
            and [t["id"] for g in pend4.values() for t in g] == [D],
            f"len={sum(len(g) for g in pend4.values())}",
        )

        # ---- errores ----
        r = await c.post("/api/pending/complete", json={"task_ids": [O]}, headers=h)
        res = r.json()
        ok("completar tarea ajena da error por tarea", r.status_code == 200 and res["completed"] == [] and "no encontrada" in res["errors"][0]["detail"], str(res))
        r = await c.post("/api/pending/complete", json={"task_ids": []}, headers=h)
        ok("lista vacía → 422", r.status_code == 422)


if __name__ == "__main__":
    asyncio.run(main())
    print("QAPEND OK")