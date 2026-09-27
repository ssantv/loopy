"""QA E2E del módulo colegio (niño): exámenes, plan, study_completions, resumen, extraescolares.

Presupone la API corriendo en http://localhost:8000. Usa un email descartable
(dominio .test lo rechaza el validador, así que usamos un email normal).
"""

import sys
from datetime import date, timedelta

import httpx

BASE = "http://localhost:8000"
EMAIL = f"colegio-qa-{__import__('time').time_ns()}@loopy.dev"
PASSWORD = "klok-2026"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"  {'ok ' if cond else 'FAIL'} {name}" + (f"  ({extra})" if extra else ""))
    if not cond:
        fail(name)


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=10)

    # ---- registro niño
    r = client.post(
        "/api/auth/register",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "profile_type": "child",
            "display_name": "NiñoQA",
            "birth_date": "2018-01-15",
            "timezone": "America/Argentina/Buenos_Aires",
        },
    )
    check("registro niño", r.status_code in (200, 201), f"status={r.status_code}")
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # ---- asignatura Lengua (1/1/1/1) con plan resumen por hojas
    r = client.post(
        "/api/subjects",
        headers=headers,
        json={"name": "Lengua", "days_resumen": 1, "days_estudio": 1, "days_practica": 1, "days_repaso": 1,
              "resumen_total_pages": 10},
    )
    check("create subject", r.status_code == 201, f"status={r.status_code}")
    subject = r.json()
    subject_id = subject["id"]

    # ---- examen 25/09 (el D-1 es 24/09 jueves)
    exam_date = date(2026, 9, 25)
    r = client.post("/api/exams", headers=headers, json={"subject_id": subject_id, "exam_date": str(exam_date)})
    check("create exam", r.status_code == 201, f"status={r.status_code}")
    exam = r.json()
    exam_id = exam["id"]
    check("exam subject_name", exam["subject_name"] == "Lengua")

    # ---- plan desde el inicio de la ventana
    r = client.get(f"/api/exams/{exam_id}/plan?from={exam_date - timedelta(days=5)}", headers=headers)
    check("GET plan", r.status_code == 200, f"status={r.status_code}")
    plan = r.json()
    items = plan["items"]
    phases = {item["date"]: item["phase"] for item in items}
    check(
        "plan ejemplo 21 resumen / 22 estudio / 23 practica / 24 repaso-final",
        phases == {
            "2026-09-21": "resumen",
            "2026-09-22": "estudio",
            "2026-09-23": "practica",
            "2026-09-24": "repaso-final",
        },
        str(phases),
    )
    check("resumen_omitted false al inicio", plan["resumen_omitted"] is False)
    check("resumen_partial false al inicio", plan["resumen_partial"] is False)

    # ---- marcar done el repaso-final (24/09) y skip un estudio
    r = client.post(f"/api/exams/{exam_id}/plan/2026-09-24", headers=headers, json={"status": "done"})
    check("mark repaso-final done", r.status_code == 200, f"status={r.status_code}")
    r = client.post(f"/api/exams/{exam_id}/plan/2026-09-22", headers=headers, json={"status": "skip"})
    check("mark estudio skip", r.status_code == 200, f"status={r.status_code}")

    r = client.get(f"/api/exams/{exam_id}/plan?from={exam_date - timedelta(days=5)}", headers=headers)
    plan = r.json()
    statuses = {item["date"]: item["status"] for item in plan["items"]}
    check("repaso-final queda done", statuses.get("2026-09-24") == "done", str(statuses))
    check("estudio salta queda skip", statuses.get("2026-09-22") == "skip")
    check("resumen queda pendiente (None)", statuses.get("2026-09-21") is None)

    # ---- undo del skip
    r = client.delete(f"/api/exams/{exam_id}/plan/2026-09-22", headers=headers)
    check("undo estudio skip", r.status_code == 200 and r.json().get("removed") is True)
    r = client.get(f"/api/exams/{exam_id}/plan?from={exam_date - timedelta(days=5)}", headers=headers)
    statuses = {item["date"]: item["status"] for item in r.json()["items"]}
    check("estudio vuelve a pendiente", statuses.get("2026-09-22") is None)

    # ---- resumen adelantado: 3 sesiones
    for _ in range(3):
        r = client.post(f"/api/subjects/{subject_id}/resumen/advance", headers=headers, json={"status": "done"})
        check("advance resumen 200", r.status_code == 200, f"status={r.status_code}")

    r = client.get("/api/subjects", headers=headers)
    subj = next(s for s in r.json() if s["id"] == subject_id)
    check("resumen_done_pages == 3", subj["resumen_done_pages"] == 3, f"done={subj['resumen_done_pages']}")

    # plan ahora: resumen parcial -> label remata
    r = client.get(f"/api/exams/{exam_id}/plan?from={exam_date - timedelta(days=5)}", headers=headers)
    plan = r.json()
    check("resumen_partial true", plan["resumen_partial"] is True)
    resumen_items = [item for item in plan["items"] if item["phase"] == "resumen"]
    check("label remata el resumen", resumen_items and "llevas 3 de 10" in (resumen_items[0]["label"] or ""),
          str([i["label"] for i in resumen_items]))

    # ---- subir a 10 páginas -> resumen se omite del plan
    for _ in range(7):
        client.post(f"/api/subjects/{subject_id}/resumen/advance", headers=headers, json={"status": "done"})
    r = client.get(f"/api/exams/{exam_id}/plan?from={exam_date - timedelta(days=5)}", headers=headers)
    plan = r.json()
    check("resumen_omitted true tras completar", plan["resumen_omitted"] is True)
    check("no quedan items fase resumen", all(i["phase"] != "resumen" for i in plan["items"]))

    # ---- undo de una sesión de resumen (vuelve a 9)
    first_adv = client.get("/api/work-sessions", headers=headers)
    today = date.today()
    r = client.delete(f"/api/subjects/{subject_id}/resumen/advance/{today}", headers=headers)
    check("undo advance resumen", r.status_code == 200, f"status={r.status_code}")
    r = client.get("/api/subjects", headers=headers)
    subj = next(s for s in r.json() if s["id"] == subject_id)
    check("resumen_done_pages == 9 tras undo", subj["resumen_done_pages"] == 9, f"done={subj['resumen_done_pages']}")

    # ---- examen repetido: marcar día ajeno al plan -> 422
    r = client.post(f"/api/exams/{exam_id}/plan/2026-09-10", headers=headers, json={"status": "done"})
    check("marcar día fuera del plan -> 422", r.status_code == 422, f"status={r.status_code}")

    # ---- update y delete exam
    r = client.patch(f"/api/exams/{exam_id}", headers=headers, json={"notes": "recuperatorio"})
    check("patch exam", r.status_code == 200 and r.json()["notes"] == "recuperatorio")
    r = client.delete(f"/api/exams/{exam_id}", headers=headers)
    check("delete exam", r.status_code == 204, f"status={r.status_code}")

    # ---- extraescolares
    r = client.post(
        "/api/extracurriculars",
        headers=headers,
        json={"name": "Natación", "day_of_week": 1, "start_time": "17:00", "end_time": "18:00"},
    )
    check("create extracurricular", r.status_code == 201, f"status={r.status_code}")
    extra_id = r.json()["id"]
    r = client.patch(f"/api/extracurriculars/{extra_id}", headers=headers, json={"end_time": "18:30"})
    check("patch extracurricular", r.status_code == 200 and r.json()["end_time"] == "18:30:00")
    r = client.get("/api/extracurriculars", headers=headers)
    check("list extracurriculars", any(e["name"] == "Natación" for e in r.json()))
    r = client.delete(f"/api/extracurriculars/{extra_id}", headers=headers)
    check("delete extracurricular", r.status_code == 204)

    # ---- work sessions
    r = client.post(
        "/api/work-sessions",
        headers=headers,
        json={"kind": "study", "planned_seconds": 1500, "actual_seconds": 1410},
    )
    check("create work session", r.status_code == 201, f"status={r.status_code}")
    r = client.get("/api/work-sessions", headers=headers)
    check("list work sessions", len(r.json()) >= 1)

    # cleanup
    client.headers.update(headers)
    client.delete("/api/auth/logout")
    print("\nE2E colegio: OK")


if __name__ == "__main__":
    main()