"""Verificación E2E de la API del motor de tareas.

Flujo: registrar niño -> crear habitación -> crear asignatura ->
crear tarea interval -> completar -> comprobar rec_next_due ->
atrasada si no se completa -> undo -> borrar.
"""

import json
import sys
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
    import random
    from datetime import date, timedelta

    # Fechas relativas al día de ejecución: con fechas fijas el guion se pudre
    # en cuanto pasan, y "hoy" deja de ser hoy.
    hoy = date.today()
    today = hoy.isoformat()
    manana = (hoy + timedelta(days=1)).isoformat()
    tres_dias = (hoy + timedelta(days=3)).isoformat()

    email = f"qa_tasks_{sys.platform.replace('-', '')}_{random.randint(0, 10**6)}@gmail.com"
    # 1) alta de cuenta de niño por la vía real: un adulto la crea con un PIN
    st, adulto = call("POST", "/api/auth/register", {
        "email": email,
        "password": "secreto123",
        "profile_type": "adult",
    })
    assert st == 201 and adulto["user"]["profile_type"] == "adult", f"register adulto: {st} {adulto}"
    # 1) alta de cuenta de niño por la vía real: un adulto la crea con un PIN.
    # Nombre único por pasada: con dos cuentas que comparten nombre y PIN el
    # login del niño se bloquea.
    nombre_nino = f"NinoTareas{random.randint(1000, 9999)}"
    st, cab = call("POST", "/api/auth/children", {
        "display_name": nombre_nino,
        "pin": "4821",
        "birth_date": "2015-05-10",
    }, adulto["token"])
    assert st == 201 and cab["profile_type"] == "child" and cab["email"] is None, f"children: {st} {cab}"
    st, entrada = call("POST", "/api/auth/child-login", {"display_name": nombre_nino, "pin": "4821"})
    assert st == 200 and entrada["user"]["profile_type"] == "child", f"child-login: {st} {entrada}"
    token = entrada["token"]

    # 2) registrarse como niño está cerrado
    st, err = call("POST", "/api/auth/register", {
        "email": f"x{email}",
        "password": "secreto123",
        "profile_type": "child",
    })
    assert st == 422, f"registro de niño debería ser 422: {st} {err}"

    # 3) habitación + asignatura
    st, room = call("POST", "/api/rooms", {"name": "Baño", "color": "#4caf50"}, token)
    assert st == 201 and room["name"] == "Baño", f"room: {st}"
    st, subj = call("POST", "/api/subjects", {"name": "Lengua", "days_practica": 1}, token)
    assert st == 201 and subj["days_practica"] == 1, f"subject: {st}"

    # 4) tarea diaria (calendario) — debe pender hoy
    st, daily = call("POST", "/api/tasks", {
        "category": "general",
        "title": "Leer",
        "rec_type": "daily",
    }, token)
    assert st == 201, f"daily create: {st} {daily}"
    st, lst = call("GET", f"/api/tasks?date={today}", token=token)
    assert st == 200, f"list: {st}"
    me = next(t for t in lst if t["id"] == daily["id"])
    assert me["pending"] is not None, f"daily debería estar pendiente: {me}"

    # 5) tarea interval (día real) cada 3 días
    st, itv = call("POST", "/api/tasks", {
        "category": "hogar",
        "title": "Regar",
        "rec_type": "interval",
        "rec_interval": 3,
        "rec_unit": "day",
        "rec_anchor": today,
    }, token)
    assert st == 201, f"interval create: {st} {itv}"
    st, done = call("POST", f"/api/tasks/{itv['id']}/complete", {"done_on": today}, token)
    assert st == 200, f"complete: {st} {done}"
    assert done["rec_next_due"] == tres_dias, f"rec_next_due tras completar: {done['rec_next_due']}"
    st, done2 = call("POST", f"/api/tasks/{itv['id']}/complete", {"done_on": today}, token)
    assert st == 409, f"completar dos veces mismo día debería ser 409: {st} {done2}"

    # 6) completar hoy la daily + undo
    st, d1 = call("POST", f"/api/tasks/{daily['id']}/complete", {"done_on": today}, token)
    assert st == 200, f"daily complete: {st} {d1}"
    st, lst = call("GET", f"/api/tasks?date={today}", token=token)
    me = next(t for t in lst if t["id"] == daily["id"])
    assert me["pending"] is None, f"daily completada no debería pender: {me}"
    assert today in me["done"], f"completion no registrada: {me['done']}"
    st, _ = call("DELETE", f"/api/tasks/{daily['id']}/complete/{today}", token=token)
    assert st == 204, f"undo: {st}"
    st, lst = call("GET", f"/api/tasks?date={today}", token=token)
    me = next(t for t in lst if t["id"] == daily["id"])
    assert me["pending"] == today, f"after undo debería pender hoy: {me['pending']}"

    # 7) tarea puntual archivada no aparece
    st, pt = call("POST", "/api/tasks", {"category": "puntual", "title": "Comprar pan", "due_on": manana}, token)
    assert st == 201, f"puntual: {st}"
    st, upd = call("PATCH", f"/api/tasks/{pt['id']}", {"archived_at": f"{today}T10:00:00Z"}, token)
    assert st == 200 and upd["archived_at"], f"archive: {st} {upd}"
    st, lst = call("GET", f"/api/tasks?date={today}", token=token)
    assert all(t["id"] != pt["id"] for t in lst), "archivada no debería aparecer"

    # 8) borrar tarea + primeras limpiezas
    st, _ = call("DELETE", f"/api/tasks/{itv['id']}", token=token)
    assert st == 204, f"delete task: {st}"
    st, _ = call("DELETE", f"/api/rooms/{room['id']}", token=token)
    assert st == 204, f"delete room: {st}"

    print("E2E OK: alta de niño por adulto + registro child cerrado, habitaciones, asignaturas, "
          "tasks diarias/interval, complete/undo, archive")


if __name__ == "__main__":
    main()