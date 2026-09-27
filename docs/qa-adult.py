"""Verificación E2E del módulo adulto.

Flujo: registrar adulto -> habitaciones + tareas de hogar -> GET /api/home
(agrupa pendientes y adelantadas por habitación) -> adelantar una tarea
(next tras hoy) -> compra (añadir, comprar, deshacer, recomendar) ->
resumen diario (config + excepciones) -> niño no puede usar compra/resumen.
"""

import json
import random
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    email = f"qa_adult_{sys.platform.replace('-', '')}_{random.randint(0, 10**6)}@gmail.com"

    st, reg = call("POST", "/api/auth/register", {
        "email": email,
        "password": "secreto123",
        "profile_type": "adult",
        "display_name": "Mayor",
    })
    assert st == 201, f"register: {st} {reg}"
    token = reg["token"]

    # --- Hogar por habitaciones ---
    st, sala = call("POST", "/api/rooms", {"name": "Sala", "color": "#aabbcc"}, token)
    assert st == 201, f"room: {st} {sala}"
    st, cocina = call("POST", "/api/rooms", {"name": "Cocina"}, token)
    assert st == 201, f"room2: {st} {cocina}"

    # Pendiente de hoy + adelantable (semanal de domingos con ancla en el próximo)
    st, t1 = call("POST", "/api/tasks", {
        "category": "hogar", "title": "Pasar la aspiradora", "room_id": sala["id"],
        "due_on": reg["user"]["created_at"][:10],  # hoy
    }, token)
    assert st == 201, f"task puntual: {st} {t1}"
    st, t2 = call("POST", "/api/tasks", {
        "category": "hogar", "title": "Regar plantas",
        "rec_type": "weekly_days", "rec_week_mask": 64,  # domingos
        "rec_anchor": "2026-09-27",
    }, token)
    assert st == 201, f"task recursiva: {st} {t2}"
    st, t3 = call("POST", "/api/tasks", {
        "category": "puntual", "title": "Llamar al fontanero", "due_on": "2026-09-24",
    }, token)
    assert st == 201, f"task futura: {st} {t3}"

    st, home = call("GET", "/api/home", token=token)
    assert st == 200, f"home: {st} {home}"
    assert home["no_room"]["pending"] == [], "puntual futura no es pendiente"
    ahead_titles = {i["title"] for i in home["no_room"]["ahead"]}
    assert ahead_titles == {"Llamar al fontanero", "Regar plantas"}, f"ahead: {home}"
    salas = [r for r in home["rooms"] if r["name"] == "Sala"][0]
    assert [i["title"] for i in salas["pending"]] == ["Pasar la aspiradora"], f"sala pending: {home}"

    # --- Adelantar: 409 si no hay, 200 si hay (consume -> next tras hoy) ---
    st, err = call("POST", f"/api/tasks/{t1['id']}/advance", {}, token)
    assert st == 409, f"puntual con due_on hoy no tiene next: {st} {err}"
    st, adv = call("POST", f"/api/tasks/{t2['id']}/advance", {}, token)
    assert st == 200, f"advance: {st} {adv}"
    assert adv["done_on"] == "2026-09-27", f"adelanta el domingo próximo: {adv}"

    # --- Compra: añadir, comprar, deshacer, recomendar ---
    st, it = call("POST", "/api/shopping", {"name": "Leche", "qty": "2 L"}, token)
    assert st == 201, f"shopping add: {st} {it}"
    st, bought = call("POST", f"/api/shopping/{it['id']}/purchase", {}, token)
    assert st == 200 and bought["purchased"], f"purchase: {st} {bought}"
    st, undo = call("POST", f"/api/shopping/{it['id']}/unpurchase", {}, token)
    assert st == 200 and not undo["purchased"], f"unpurchase: {st} {undo}"
    st, err = call("DELETE", f"/api/shopping/{it['id']}", {}, token)
    assert st == 204, f"quitar pendiente: {st} {err}"
    # recomendación: dos compras de 'Pan' en 90 días + una tercera
    for _ in range(2):
        st, p = call("POST", "/api/shopping", {"name": "pan", "qty": "1"}, token)
        assert st == 201, f"add pan: {st} {p}"
        st, _ = call("POST", f"/api/shopping/{p['id']}/purchase", {}, token)
        assert st == 200, "purchase pan"
    st, rec = call("GET", "/api/shopping/recommend", token=token)
    assert st == 200, f"recommend: {st} {rec}"
    assert any(r["name"].lower() == "pan" and r["count"] == 2 for r in rec), f"pan recomendado: {rec}"
    # compra de niño bloqueada
    st, kid = call("POST", "/api/auth/register", {
        "email": email.replace("adult", "kid"),
        "password": "secreto123", "profile_type": "child", "birth_date": "2016-01-01",
    })
    assert st == 201, f"register kid: {st} {kid}"
    st, blocked = call("GET", "/api/shopping", token=kid["token"])
    assert st == 403, f"compra de niño debería ser 403: {st} {blocked}"

    # --- Resumen diario: config + excepciones ---
    st, conf = call("GET", "/api/summary/config", token=token)
    assert st == 200 and conf["enabled"] and conf["time"] == "20:00:00", f"config defaults: {conf}"
    st, conf2 = call("PATCH", "/api/summary/config", {"time": "21:30"}, token)
    assert st == 200 and conf2["time"] == "21:30:00", f"patch config: {conf2}"
    st, exc = call("PUT", "/api/summary/exceptions/2026-09-25", {"action": "skip"}, token)
    assert st == 200 and exc["action"] == "skip", f"exception: {exc}"
    st, mon = call("GET", "/api/summary?month=2026-09", token=token)
    assert st == 200 and [d["date"] for d in mon["days"]] == ["2026-09-25"], f"mes: {mon}"
    st, _ = call("DELETE", "/api/summary/exceptions/2026-09-25", {}, token)
    assert st == 204, "borra excepción"
    st, blocked = call("GET", "/api/summary/config", token=kid["token"])
    assert st == 403, f"resumen de niño debería ser 403: {st} {blocked}"

    print("E2E OK: hogar por habitaciones (pendientes + adelantadas), advance (next tras hoy, 409 si no hay), "
          "compra (añadir/comprar/deshacer/quitar/recomendar), resumen diario (config + excepciones), "
          "protección adulto")


if __name__ == "__main__":
    main()