#!/usr/bin/env python
"""QA backend del paso 8 (Menú de comidas).

Comprueba contra la API real en localhost:
1. Franjas: defaults apagadas, activación por PATCH.
2. Categorías globales + objetivos por defecto, override y reset vía PATCH/DELETE.
3. Recetas: alta con ingredientes y franjas, edición, listado.
4. Plan semanal: asignar receta/texto libre, incompatibilidad de franja (409),
   copiar semana y recomendar huecos.
5. A la compra: fusión por nombre normalizado, suma de cantidades.
6. Perfil niño → 403.

Requisitos: API corriendo en 127.0.0.1:8000 con DB SQLite dev.
"""
import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"
DB = Path(__file__).resolve().parent.parent / "api" / "loopy_dev.db"


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


def monday_of(d: date) -> date:
    return d - timedelta(days=(d.isoweekday() - 1))


async def main() -> None:
    today = datetime.now().astimezone().date()
    mon = monday_of(today)
    next_mon = mon + timedelta(days=7)

    email = f"qa_menu_{uuid.uuid4().hex[:10]}@test.com"
    child_email = f"qa_menu_child_{uuid.uuid4().hex[:10]}@test.com"
    password = "secret123"

    async with httpx.AsyncClient(base_url=API, timeout=10) as c:
        reg = (await c.post("/api/auth/register", json={"email": email, "password": password})).json()
        h = {"Authorization": f"Bearer {reg['token']}"}

        # ---- franjas ----
        slots = (await c.get("/api/menu/slots", headers=h)).json()["slots"]
        ok("slots defaults: 5 y todas apagadas", len(slots) == 5 and all(not s["enabled"] for s in slots))
        patched = (await c.patch("/api/menu/slots/comida", json={"enabled": True}, headers=h)).json()
        await c.patch("/api/menu/slots/cena", json={"enabled": True}, headers=h)
        ok("PATCH comida habilita", patched["enabled"] is True and patched["slot"] == "comida")
        after = (await c.get("/api/menu/slots", headers=h)).json()["slots"]
        ok(
            "persistido",
            {s["slot"]: s["enabled"] for s in after} == {"desayuno": False, "almuerzo": False, "comida": True, "merienda": False, "cena": True},
        )

        # ---- categorías + objetivos ----
        cats = (await c.get("/api/menu/categories", headers=h)).json()
        by_name = {x["name"]: x for x in cats}
        ok("6 categorías globales", len(cats) == 6 and set(by_name) == {"pescado", "verdura", "legumbre", "carne", "huevo", "pasta/arroz"})
        goals = {g["name"]: g for g in (await c.get("/api/menu/goals", headers=h)).json()}
        ok(
            "objetivos por defecto",
            goals["pescado"]["min_per_week"] == 2
            and goals["verdura"]["min_per_week"] == 4
            and goals["carne"] == {"category_id": by_name["carne"]["id"], "name": "carne", "min_per_week": 2, "max_per_week": 3, "is_default": True},
        )
        override = (await c.patch(f"/api/menu/goals/{by_name['carne']['id']}", json={"min_per_week": 3, "max_per_week": None}, headers=h)).json()
        ok("override carne 3/sin máx", override["min_per_week"] == 3 and override["max_per_week"] is None and override["is_default"] is False)
        r = await c.delete(f"/api/menu/goals/{by_name['carne']['id']}", headers=h)
        reset = {g["name"]: g for g in (await c.get("/api/menu/goals", headers=h)).json()}
        ok("DELETE restaura default", r.status_code == 204 and reset["carne"]["min_per_week"] == 2)

        # ---- recetas ----
        payload = {
            "name": "pollo al horno",
            "category_id": by_name["carne"]["id"],
            "slots": ["comida", "cena"],
            "notes": "con patatas",
            "ingredients": [{"name": "pollo", "qty": 1, "unit": "kg"}, {"name": "patatas", "qty": 4, "unit": "ud"}],
        }
        rec = (await c.post("/api/menu/recipes", json=payload, headers=h)).json()
        ok(
            "receta creada",
            rec["name"] == "pollo al horno" and sorted(rec["slots"]) == ["cena", "comida"] and len(rec["ingredients"]) == 2,
            f"id={rec['id']}",
        )
        rec2 = (await c.post("/api/menu/recipes", json={**payload, "name": "lentejas", "category_id": by_name["legumbre"]["id"], "slots": ["comida"], "ingredients": [{"name": "lentejas", "qty": 300, "unit": "g"}]}, headers=h)).json()
        listing = (await c.get("/api/menu/recipes", headers=h)).json()
        ok("listado incluye ambas", {r["name"] for r in listing} == {"pollo al horno", "lentejas"})
        renamed = (await c.patch(f"/api/menu/recipes/{rec['id']}", json={"notes": "con pan"}, headers=h)).json()
        ok("PATCH notas", renamed["notes"] == "con pan")

        # ---- plan: asignar + incompatibilidad + copy + recomendar ----
        plan = (await c.get(f"/api/menu/plan?start={mon}", headers=h)).json()
        ok("plan inicial vacío", plan["plans"] == [] and plan["start"] == str(mon))

        good = (await c.put(f"/api/menu/plan/{mon}/{('comida')}", json={"recipe_id": rec["id"]}, headers=h)).json()
        ok("asignar pollo en comida", good["recipe_name"] == "pollo al horno")
        r = await c.put(f"/api/menu/plan/{mon}/desayuno", json={"recipe_id": rec["id"]}, headers=h)  # receta solo comida/cena
        ok("receta incompatible con desayuno → 409", r.status_code == 409)
        txt = (await c.put(f"/api/menu/plan/{mon}/cena", json={"free_text": "pizza"}, headers=h)).json()
        ok("texto libre en cena", txt["free_text"] == "pizza")

        res = await c.post("/api/menu/plan/copy", json={"from_date": str(mon), "to_date": str(next_mon)}, headers=h)
        ok("copiar semana", res.status_code == 200 and res.json()["copied"] == 2, str(res.json()))
        dst = (await c.get(f"/api/menu/plan?start={next_mon}", headers=h)).json()["plans"]
        ok(
            "copia aplicada al destino",
            {p["slot"] for p in dst if p["recipe_name"]} == {"comida"} and {p["slot"] for p in dst if p["free_text"]} == {"cena"},
        )

        # vaciar destino para probar recomendar en huecos
        for p in dst:
            await c.delete(f"/api/menu/plan/{p['date']}/{p['slot']}", headers=h)
        rec_res = (await c.post("/api/menu/plan/recommend", json={"start": str(next_mon)}, headers=h)).json()
        ok(
            "recomendar rellena huecos",
            rec_res["filled"] > 0 and all(p["recipe_id"] for p in rec_res["plans"]),
            f"filled={rec_res['filled']}",
        )
        plans_after = (await c.get(f"/api/menu/plan?start={next_mon}", headers=h)).json()["plans"]
        ok("plan destino ya no está vacío", rec_res["filled"] > 0 and len(plans_after) == rec_res["filled"], f"plans={len(plans_after)} filled={rec_res['filled']}")

        # ---- a la compra ----
        res = await c.post("/api/menu/shopping", json={"start": str(next_mon)}, headers=h)
        ok("añadir semana a compra", res.status_code == 200 and res.json()["created"] >= 1, str(res.json()))
        # Añadir la misma receta ya en la compra → actualiza, no crea
        res = await c.post("/api/menu/shopping", json={"recipe_id": rec["id"]}, headers=h)
        ok("añadir receta existente fusiona", res.status_code == 200 and res.json()["updated"] >= 1 and res.json()["created"] == 0, str(res.json()))
        res = await c.post("/api/menu/shopping", json={"recipe_id": rec["id"]}, headers=h)
        ok("repetir receta fusiona", res.json()["updated"] >= 1 and res.json()["created"] == 0, str(res.json()))
        items = (await c.get("/api/shopping", headers=h)).json()
        pollo = [i for i in items if i["name"] == "pollo"]
        ok("pollo pendiente con 5 kg (3 semana + 2 recetas)", pollo and pollo[0]["qty"] == "5 kg" and pollo[0]["source"] == "plan", str(pollo))

        # ---- limpieza ----
        r = await c.delete(f"/api/menu/recipes/{rec['id']}", headers=h)
        r2 = await c.delete(f"/api/menu/recipes/{rec2['id']}", headers=h)
        ok("borrar recetas", r.status_code == 204 and r2.status_code == 204)

        # ---- niño → 403 ----
        regc = (await c.post("/api/auth/register", json={"email": child_email, "password": password, "profile_type": "child", "birth_date": "2015-01-01"})).json()
        hc = {"Authorization": f"Bearer {regc['token']}"}
        r = await c.get("/api/menu/slots", headers=hc)
        ok("perfil niño → 403", r.status_code == 403)


if __name__ == "__main__":
    asyncio.run(main())
    print("QAMENU OK")