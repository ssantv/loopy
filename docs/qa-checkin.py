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

    # 1) Niño nacido en 2015 -> ~11 años -> tono 'cercano' (tone_source auto)
    st, reg = call("POST", "/api/auth/register", {
        "email": email,
        "password": "secreto123",
        "profile_type": "child",
        "birth_date": "2015-05-10",
        "display_name": "Mini",
    })
    assert st == 201, f"register: {st} {reg}"
    assert reg["user"]["notification_tone"] == "cercano", f"tono inicial: {reg['user']}"
    assert reg["user"]["tone_source"] == "auto", "tone_source debería ser auto"
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
    assert deber["due_on"] == quick["day"], f"deberes del día: {deber}"
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