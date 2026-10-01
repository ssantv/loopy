"""Verificación E2E del check-in diario del niño.

Flujo: registrar niño -> tono sugerido por edad -> GET config (defaults) ->
PATCH config -> GET tone -> alta rápida (deber + examen + proyecto) ->
comprobar tareas/exámenes creados -> adulto no puede usar el check-in.
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

    email = f"qa_checkin_{sys.platform.replace('-', '')}_{random.randint(0, 10**6)}@gmail.com"
    # El nombre del niño es su clave de entrada: único por pasada, porque con
    # dos cuentas que comparten nombre y PIN la entrada se bloquea.
    nombre = f"Mini{random.randint(1000, 9999)}"

    # 1) Niño nacido en 2015 -> ~11 años -> tono 'cercano' (tone_source auto).
    #    La cuenta la crea un adulto con un PIN: no hay registro de niño.
    st, adulto = call("POST", "/api/auth/register", {
        "email": email,
        "password": "secreto123",
        "profile_type": "adult",
    })
    assert st == 201, f"register adulto: {st} {adulto}"
    st, cab = call("POST", "/api/auth/children", {
        "display_name": nombre,
        "pin": "4821",
        "birth_date": "2015-05-10",
    }, adulto["token"])
    assert st == 201, f"alta de niño: {st} {cab}"
    assert cab["notification_tone"] == "cercano", f"tono inicial: {cab}"
    assert cab["tone_source"] == "auto", "tone_source debería ser auto"
    st, reg = call("POST", "/api/auth/child-login", {"display_name": nombre, "pin": "4821"})
    assert st == 200, f"child-login: {st} {reg}"
    token = reg["token"]

    # 2) Config por defecto (se crea al consultar)
    st, conf = call("GET", "/api/checkin/config", token=token)
    assert st == 200, f"get config: {st} {conf}"
    assert conf["enabled"] is True and conf["time"] == "20:00:00" and conf["week_mask"] == 127, f"defaults: {conf}"

    # 3) PATCH config
    st, conf2 = call("PATCH", "/api/checkin/config", {"enabled": False, "time": "19:30", "week_mask": 31}, token)
    assert st == 200, f"patch config: {st} {conf2}"
    assert conf2["enabled"] is False and conf2["time"] == "19:30:00" and conf2["week_mask"] == 31, f"patched: {conf2}"

    # 4) Tono con plantilla del check-in
    st, tone = call("GET", "/api/checkin/tone", token=token)
    assert st == 200, f"get tone: {st} {tone}"
    assert tone["notification_tone"] == "cercano"
    assert tone["template"].startswith("¡Hola!"), f"tone: {tone}"

    # 5) Asignatura para el examen
    st, subj = call("POST", "/api/subjects", {"name": "Inglés", "days_practica": 1}, token)
    assert st == 201, f"subject: {st} {subj}"

    # 6) Alta rápida: deber + examen + proyecto
    items = [
        {"type": "deber", "title": "Librillo de mates", "subject_id": subj["id"], "est_minutes": 25,
         "pending_from_class": True},
        {"type": "examen", "subject_id": subj["id"], "exam_date": "2026-10-05", "notes": "listening"},
        {"type": "proyecto", "title": "Trabajo de ciencias", "est_minutes": 120, "due_on": "2026-10-15"},
    ]
    st, quick = call("POST", "/api/checkin/items", {"items": items}, token)
    assert st == 201, f"quick add: {st} {quick}"
    assert len(quick["deberes"]) == 1, quick
    assert len(quick["proyectos"]) == 1, quick
    assert len(quick["examenes"]) == 1, quick
    deber = quick["deberes"][0]
    proyecto = quick["proyectos"][0]
    examen = quick["examenes"][0]
    assert deber["pending_from_class"] is True and deber["est_minutes"] == 25, deber
    # Desde la Fase 2b un deber de asignatura no vence "hoy": vence el próximo
    # día de clase de esa asignatura, saltando los días sin cole. El día del
    # check-in es cuándo te lo pusieron, no cuándo hay que entregarlo.
    assert deber["due_on"] > quick["day"], f"el deber debería vencer después de ponerle: {deber}"
    assert deber["due_from_rule"] == "próximo día de clase", deber
    assert deber["assigned_on"] == quick["day"], deber
    # El proyecto con fecha puesta a mano manda él: no lo recalcula.
    assert proyecto["due_on"] == "2026-10-15", proyecto
    assert examen["subject_name"] == "Inglés", examen

    # 7) Los objetos quedan creados y visibles
    st, tasks = call("GET", "/api/tasks", token=token)
    assert st == 200
    ids = {t["id"] for t in tasks}
    assert deber["id"] in ids and proyecto["id"] in ids, "tareas no creadas"
    st, exams = call("GET", "/api/exams", token=token)
    assert st == 200 and {e["id"] for e in exams} == {examen["id"]}, "examen no creado"

    # 8) Adulto no puede usar el check-in
    st, regA = call("POST", "/api/auth/register", {
        "email": f"a{email}", "password": "secreto123", "profile_type": "adult",
    })
    assert st == 201, f"register adult: {st} {regA}"
    st, blocked = call("POST", "/api/checkin/items", {"items": [{"type": "deber", "title": "x"}]}, regA["token"])
    assert st == 403, f"adult quick add debería ser 403: {st} {blocked}"

    print("E2E OK: tono por edad, config check-in (defaults + patch), tone, alta rápida deber/examen/proyecto, "
          "protección adulto")


if __name__ == "__main__":
    main()