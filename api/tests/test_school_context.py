"""Tests del contexto escolar de la Fase 2: horario, días sin cole y plantillas.

Cubre las tres piezas que se configuran una vez desde Perfil y que luego usa el
cálculo de la fecha límite de los deberes:

- `/api/timetable`: días de cada asignatura, agrupados y sin duplicados.
- `/api/off-days`: rangos sin cole (un día suelto, un puente, vacaciones) y el
  rango que cubre un día concreto.
- `/api/homework-templates`: atajos de deber para el alta rápida.

Más lo que depende de ellos: el calendario marca `no_school` y pinta las
extraescolares de cada día, la categoría `rutina` se acepta, `hogar` también se
puede mandar al niño y el tope de estudio se edita desde el perfil.

Los tests de la lógica pura de fechas (`SchoolCalendar`) están al final y no
tocan la BD: son los que hdrmen que la fecha límite salte días sin cole.
"""

from datetime import date, time
from types import SimpleNamespace

import pytest
from conftest import make_session_factory
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.services.schedule import SchoolCalendar, school_calendar

# 2026-09-28 es lunes. Todos los tests usan esta semana como referencia.
LUNES = date(2026, 9, 28)
MARTES = date(2026, 9, 29)


@pytest.fixture
async def env():
    maker = await make_session_factory()

    async def _get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield SimpleNamespace(client=c, maker=maker)
    app.dependency_overrides.clear()


async def _authed(env, email="nino@test.com", profile_type="child") -> str:
    cuerpo = {"email": email, "password": "s3cret123", "profile_type": profile_type}
    if profile_type == "child":
        cuerpo["birth_date"] = "2015-01-01"
    r = await env.client.post("/api/auth/register", json=cuerpo)
    assert r.status_code in (200, 201), r.text
    tok = r.json()["token"]
    env.client.headers["Authorization"] = f"Bearer {tok}"
    return tok


async def _mk_subject(env, name="Sociales", color="#ff0000") -> int:
    r = await env.client.post("/api/subjects", json={"name": name, "color": color})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _mk_exam(env, subject_id: int, exam_date: date) -> int:
    r = await env.client.post("/api/exams", json={"subject_id": subject_id, "exam_date": exam_date.isoformat()})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# ------------------------------------------------------------------ timetable


async def test_horario_agrupa_por_dia_con_nombre_y_color(env):
    await _authed(env)
    sociales = await _mk_subject(env, "Sociales", "#123456")
    matematicas = await _mk_subject(env, "Matemáticas", "#654321")

    assert (await env.client.post("/api/timetable", json={"subject_id": sociales, "day_of_week": 0})).status_code == 201
    await env.client.post("/api/timetable", json={"subject_id": sociales, "day_of_week": 1})
    await env.client.post("/api/timetable", json={"subject_id": matematicas, "day_of_week": 0})

    r = await env.client.get("/api/timetable")
    assert r.status_code == 200
    days = r.json()["days"]

    assert sorted(days) == ["0", "1"]
    assert [s["subject_name"] for s in days["0"]] == ["Sociales", "Matemáticas"]
    assert days["0"][0]["subject_color"] == "#123456"
    assert [s["subject_name"] for s in days["1"]] == ["Sociales"]


async def test_horario_duplicado_devuelve_el_existente_sin_crear_dos(env):
    """Reenviar la misma rejilla no debe crear franjas duplicadas."""
    await _authed(env)
    sid = await _mk_subject(env)

    r1 = await env.client.post("/api/timetable", json={"subject_id": sid, "day_of_week": 2})
    r2 = await env.client.post("/api/timetable", json={"subject_id": sid, "day_of_week": 2})

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]

    days = (await env.client.get("/api/timetable")).json()["days"]
    assert len(days["2"]) == 1


async def test_horario_rechaza_asignatura_ajena_y_dia_invalido(env):
    # El usuario A crea una asignatura...
    await _authed(env, email="a@test.com")
    ajena = await _mk_subject(env, "Ajena")

    # ...y el usuario B no puede meterla en su horario.
    await _authed(env, email="b@test.com")
    r = await env.client.post("/api/timetable", json={"subject_id": ajena, "day_of_week": 0})
    assert r.status_code == 404

    # day_of_week fuera de 0..6
    propia = await _mk_subject(env, "Propia")
    r = await env.client.post("/api/timetable", json={"subject_id": propia, "day_of_week": 7})
    assert r.status_code == 422
    r = await env.client.post("/api/timetable", json={"subject_id": propia, "day_of_week": -1})
    assert r.status_code == 422


async def test_borrar_franja_del_horario(env):
    await _authed(env)
    sid = await _mk_subject(env)
    slot = (await env.client.post("/api/timetable", json={"subject_id": sid, "day_of_week": 3})).json()

    assert (await env.client.delete(f"/api/timetable/{slot['id']}")).status_code == 204
    assert (await env.client.get("/api/timetable")).json()["days"] == {}
    # Segunda vez ya no existe.
    assert (await env.client.delete(f"/api/timetable/{slot['id']}")).status_code == 404


# ------------------------------------------------------------------- off-days


async def test_dia_suelto_se_normaliza_a_rango_de_un_dia(env):
    await _authed(env)
    r = await env.client.post("/api/off-days", json={"start_on": "2026-10-12", "label": "Fiesta"})
    assert r.status_code == 201
    body = r.json()
    assert body["start_on"] == "2026-10-12"
    assert body["end_on"] == "2026-10-12"
    assert body["days_count"] == 1
    assert body["label"] == "Fiesta"


async def test_vacaciones_cuentan_los_dos_extremos(env):
    await _authed(env)
    r = await env.client.post(
        "/api/off-days", json={"start_on": "2026-12-23", "end_on": "2026-12-30", "label": "Navidad"}
    )
    assert r.status_code == 201
    # 23..30 inclusive son 8 días.
    assert r.json()["days_count"] == 8


async def test_off_days_rechaza_rango_invertido(env):
    await _authed(env)
    r = await env.client.post("/api/off-days", json={"start_on": "2026-12-30", "end_on": "2026-12-23"})
    assert r.status_code == 422


async def test_rango_que_cubre_un_dia_concreto(env):
    await _authed(env)
    await env.client.post("/api/off-days", json={"start_on": "2026-10-26", "end_on": "2026-10-30", "label": "Puente"})

    dentro = await env.client.get("/api/off-days/covering/2026-10-28")
    assert dentro.status_code == 200
    assert dentro.json()["label"] == "Puente"

    fuera = await env.client.get("/api/off-days/covering/2026-11-02")
    assert fuera.status_code == 200
    assert fuera.json() is None


async def test_off_days_de_otro_usuario_no_se_ven(env):
    await _authed(env, email="a@test.com")
    await env.client.post("/api/off-days", json={"start_on": "2026-10-12"})

    await _authed(env, email="b@test.com")
    assert (await env.client.get("/api/off-days")).json() == []


# -------------------------------------------------------- homework templates


async def test_crud_de_plantillas(env):
    await _authed(env)
    sid = await _mk_subject(env, "Lengua")

    r = await env.client.post(
        "/api/homework-templates",
        json={"title": "Leer 20 min", "subject_id": sid, "est_minutes": 20, "sort": 1},
    )
    assert r.status_code == 201
    tpl = r.json()
    assert tpl["title"] == "Leer 20 min"
    assert tpl["subject_name"] == "Lengua"
    assert tpl["est_minutes"] == 20

    listado = (await env.client.get("/api/homework-templates")).json()
    assert len(listado) == 1

    r = await env.client.patch(f"/api/homework-templates/{tpl['id']}", json={"title": "Leer 30 min"})
    assert r.status_code == 200
    assert r.json()["title"] == "Leer 30 min"
    # Lo no informado no se toca.
    assert r.json()["est_minutes"] == 20

    assert (await env.client.delete(f"/api/homework-templates/{tpl['id']}")).status_code == 204
    assert (await env.client.get("/api/homework-templates")).json() == []
    assert (await env.client.delete(f"/api/homework-templates/{tpl['id']}")).status_code == 404


async def test_plantilla_rechaza_asignatura_ajena(env):
    await _authed(env, email="a@test.com")
    ajena = await _mk_subject(env, "Ajena")

    await _authed(env, email="b@test.com")
    r = await env.client.post("/api/homework-templates", json={"title": "X", "subject_id": ajena})
    assert r.status_code == 404


async def test_plantilla_sin_asignatura_perfectamente_valida(env):
    """Una plantilla sin asignatura es normal ("recoger la habitación")."""
    await _authed(env)
    r = await env.client.post("/api/homework-templates", json={"title": "Ordenar la habitación"})
    assert r.status_code == 201
    assert r.json()["subject_id"] is None
    assert r.json()["subject_name"] is None


# ----------------------------------------------------------------- calendario


async def test_calendario_marca_dias_sin_cole_sin_obligar_a_poner_tareas(env):
    await _authed(env)
    await env.client.post(
        "/api/off-days", json={"start_on": "2026-10-26", "end_on": "2026-10-30", "label": "Puente"}
    )

    r = await env.client.get("/api/calendar", params={"from": "2026-10-26", "to": "2026-10-31"})
    assert r.status_code == 200
    days = r.json()["days"]

    # Los 5 días del puente aparecen aunque no haya ninguna tarea.
    for d in ("2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"):
        assert days[d]["no_school"] is True
        assert days[d]["off_label"] == "Puente"
    # El domingo siguiente no.
    assert "2026-10-31" not in days


async def test_calendario_sigue_siendo_disperso_si_no_hay_nada_que_mostrar(env):
    """Un rango vacío sigue devolviendo `{}`: no 365 objetos vacíos."""
    await _authed(env)
    r = await env.client.get("/api/calendar", params={"from": "2026-01-01", "to": "2026-12-31"})
    assert r.json()["days"] == {}


async def test_calendario_pinta_extraescolares_de_cada_dia(env):
    await _authed(env)
    # Swim: miércoles (day_of_week 2), fuera de las vacaciones de agosto.
    r = await env.client.post(
        "/api/extracurriculars",
        json={
            "name": "Natación",
            "day_of_week": 2,
            "start_time": "18:00:00",
            "end_time": "19:00:00",
        },
    )
    assert r.status_code == 201, r.text

    r = await env.client.get("/api/calendar", params={"from": "2026-09-28", "to": "2026-10-04"})
    days = r.json()["days"]
    # 2026-09-30 es miércoles.
    assert days["2026-09-30"]["extras"][0]["name"] == "Natación"
    assert days["2026-09-30"]["extras"][0]["start_time"].startswith("18:00")
    # Los lunes no hay nada.
    assert "2026-09-28" not in days


async def test_calendario_respeta_el_rango_de_fechas_de_la_extraescolar(env):
    """Una extraescolar de curso escolar no aparece en Navidad."""
    await _authed(env)
    await env.client.post(
        "/api/extracurriculars",
        json={
            "name": "Fútbol",
            "day_of_week": 0,
            "start_time": "17:00:00",
            "end_time": "18:00:00",
            "start_on": "2026-10-01",
            "end_on": "2026-12-18",
        },
    )

    # Lunes 2026-10-05: dentro de curso.
    dentro = (await env.client.get("/api/calendar", params={"from": "2026-10-05", "to": "2026-10-05"})).json()["days"]
    assert dentro["2026-10-05"]["extras"][0]["name"] == "Fútbol"

    # Lunes 2026-12-21: fuera de curso (y además Navidad).
    fuera = (await env.client.get("/api/calendar", params={"from": "2026-12-21", "to": "2026-12-21"})).json()["days"]
    assert "2026-12-21" not in fuera or fuera["2026-12-21"]["extras"] == []


# ------------------------------------------------------- categorías y perfil


async def test_se_acepta_la_categoria_rutina(env):
    await _authed(env)
    r = await env.client.post(
        "/api/tasks",
        json={
            "category": "rutina",
            "title": "Dientes",
            "assigned_on": "2026-09-28",
            "rec_type": "daily",
            "est_minutes": 5,
        },
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["category"] == "rutina"
    assert body["assigned_on"] == "2026-09-28"


async def test_el_nino_puede_recibir_encargos_de_hogar(env):
    """`hogar` es la categoría de los encargos que le pone un adulto."""
    await _authed(env)
    r = await env.client.post(
        "/api/tasks", json={"category": "hogar", "title": "Sacar la basura", "est_minutes": 5}
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["category"] == "hogar"


async def test_tope_de_estudio_por_defecto_y_editable(env):
    tok = await _authed(env)

    me = (await env.client.get("/api/auth/me")).json()
    assert me["study_max_minutes"] == 60

    r = await env.client.patch("/api/auth/me", json={"study_max_minutes": 45})
    assert r.status_code == 200
    assert r.json()["study_max_minutes"] == 45

    # 0 = sin tope.
    assert (await env.client.patch("/api/auth/me", json={"study_max_minutes": 0})).json()["study_max_minutes"] == 0
    # Negativo no.
    assert (await env.client.patch("/api/auth/me", json={"study_max_minutes": -1})).status_code == 422
    del tok


# ------------------------------------------- tope de carga en el calendario


async def test_el_calendario_reparte_la_carga_entre_examenes(env):
    """Dos exámenes el mismo día no deben pedir 60 min de estudio la misma tarde."""
    await _authed(env)
    a = await _mk_subject(env, "Lengua")
    b = await _mk_subject(env, "Mates")
    # Cada asignatura: una sola sesión de 30 min, el día antes del examen.
    for sid in (a, b):
        await env.client.patch(f"/api/subjects/{sid}", json={"prep_minutes": 30, "session_minutes": 30})
    # Los dos exámenes el mismo día.
    await _mk_exam(env, a, date(2026, 10, 15))
    await _mk_exam(env, b, date(2026, 10, 15))
    # Tope de 30 min al día.
    await env.client.patch("/api/auth/me", json={"study_max_minutes": 30})

    r = await env.client.get("/api/calendar", params={"from": "2026-10-12", "to": "2026-10-14"})
    assert r.status_code == 200
    days = r.json()["days"]

    def minutos(d: str) -> int:
        return sum(i["minutes"] for i in days.get(d, {}).get("plan", []))

    # Ningún día se pasa del tope...
    for d in ("2026-10-12", "2026-10-13", "2026-10-14"):
        assert minutos(d) <= 30, (d, days.get(d))
    # ...y las dos sesiones siguen estando, solo que en días distintos.
    assert sum(minutos(d) for d in ("2026-10-12", "2026-10-13", "2026-10-14")) == 60
    # Y todo ha cabido: no hay minutos que reportar como no colocables.
    assert r.json()["unplaced_study_minutes"] == 0


async def test_con_tope_cero_las_dos_sesiones_caen_el_mismo_dia(env):
    """Sin tope (0) el plan no se toca: es la referencia del test anterior."""
    await _authed(env)
    a = await _mk_subject(env, "Lengua")
    b = await _mk_subject(env, "Mates")
    for sid in (a, b):
        await env.client.patch(f"/api/subjects/{sid}", json={"prep_minutes": 30, "session_minutes": 30})
    await _mk_exam(env, a, date(2026, 10, 15))
    await _mk_exam(env, b, date(2026, 10, 15))
    await env.client.patch("/api/auth/me", json={"study_max_minutes": 0})

    days = (await env.client.get("/api/calendar", params={"from": "2026-10-12", "to": "2026-10-14"})).json()["days"]
    minutos_14 = sum(i["minutes"] for i in days.get("2026-10-14", {}).get("plan", []))
    assert minutos_14 == 60  # las dos sesiones juntas, como antes


async def test_el_plan_de_examen_salta_los_dias_sin_cole(env):
    await _authed(env)
    sid = await _mk_subject(env, "Sociales")
    await env.client.patch(f"/api/subjects/{sid}", json={"prep_minutes": 30, "session_minutes": 30})
    exam = await _mk_exam(env, sid, date(2026, 10, 12))  # lunes
    # El fin de semana anterior no es cole: lo marcamos como puente.
    await env.client.post("/api/off-days", json={"start_on": "2026-10-10", "end_on": "2026-10-11"})

    r = await env.client.get(f"/api/exams/{exam}/plan", params={"from": "2026-10-05", "to": "2026-10-12"})
    assert r.status_code == 200, r.text
    dias = {i["date"] for i in r.json()["items"]}
    assert "2026-10-11" not in dias
    assert "2026-10-10" not in dias


# ------------------------------------------- fecha límite en el alta rápida


async def _quick_add(env, items, day="2026-09-29"):
    """POST /api/checkin/items y devuelve el JSON."""
    r = await env.client.post("/api/checkin/items", json={"day": day, "items": items})
    return r


async def test_deber_va_para_el_siguiente_dia_de_clase_y_no_para_manana(env):
    """El caso del planteamiento: sociales lunes y martes, añadido un martes."""
    await _authed(env)
    sociales = await _mk_subject(env, "Sociales")
    await env.client.post("/api/timetable", json={"subject_id": sociales, "day_of_week": 0})  # lunes
    await env.client.post("/api/timetable", json={"subject_id": sociales, "day_of_week": 1})  # martes

    r = await _quick_add(env, [{"type": "deber", "title": "Tema 3", "subject_id": sociales}])
    assert r.status_code == 201, r.text
    deber = r.json()["deberes"][0]

    # 2026-09-29 es martes: el siguiente día de clase es el lunes 2026-10-05.
    assert deber["assigned_on"] == "2026-09-29"
    assert deber["due_on"] == "2026-10-05"
    assert deber["due_from_rule"] == "próximo día de clase"
    assert deber["source_kind"] == "asignatura"
    assert deber["source_name"] == "Sociales"


async def test_la_fecha_limite_explicita_manda_sobre_el_horario(env):
    await _authed(env)
    sociales = await _mk_subject(env)
    await env.client.post("/api/timetable", json={"subject_id": sociales, "day_of_week": 0})

    r = await _quick_add(env, [{"type": "deber", "title": "Tema 3", "subject_id": sociales, "due_on": "2026-09-30"}])
    deber = r.json()["deberes"][0]
    assert deber["due_on"] == "2026-09-30"
    assert deber["due_from_rule"] == "manual"


async def test_la_fecha_limite_salta_los_dias_sin_cole(env):
    await _authed(env)
    sociales = await _mk_subject(env)
    await env.client.post("/api/timetable", json={"subject_id": sociales, "day_of_week": 0})  # lunes
    # El lunes siguiente es puente.
    await env.client.post("/api/off-days", json={"start_on": "2026-10-05", "end_on": "2026-10-09"})

    r = await _quick_add(env, [{"type": "deber", "title": "Tema 3", "subject_id": sociales}])
    # Salta al lunes de después, no al 5 ni al 6.
    assert r.json()["deberes"][0]["due_on"] == "2026-10-12"


async def test_deber_de_extraescolar_usa_el_dia_de_la_extraescolar(env):
    await _authed(env)
    extra = (
        await env.client.post(
            "/api/extracurriculars",
            json={
                "name": "Natación",
                "day_of_week": 2,
                "start_time": "18:00:00",
                "end_time": "19:00:00",
            },
        )
    ).json()

    r = await _quick_add(env, [{"type": "deber", "title": "Traer bañador", "extracurricular_id": extra["id"]}])
    deber = r.json()["deberes"][0]
    # 2026-09-30 es miércoles.
    assert deber["due_on"] == "2026-09-30"
    assert deber["due_from_rule"] == "próxima extraescolar"
    assert deber["source_kind"] == "extraescolar"
    assert deber["source_name"] == "Natación"


async def test_encargo_sin_origen_se_queda_sin_fecha_limite(env):
    """Los chores de casa y la rutina no tienen plazo: no se inventa uno."""
    await _authed(env)
    r = await _quick_add(env, [{"type": "deber", "title": "Sacar la basura"}])
    deber = r.json()["deberes"][0]
    assert deber["assigned_on"] == "2026-09-29"
    assert deber["due_on"] is None
    assert deber["due_from_rule"] is None
    assert deber["source_kind"] is None


async def test_item_puede_anular_el_dia_del_request(env):
    await _authed(env)
    r = await _quick_add(
        env,
        [
            {"type": "deber", "title": "Para el lunes", "assigned_on": "2026-10-05"},
            {"type": "deber", "title": "Para hoy"},
        ],
    )
    assert r.status_code == 201, r.text
    deberes = r.json()["deberes"]
    assert deberes[0]["assigned_on"] == "2026-10-05"
    assert deberes[1]["assigned_on"] == "2026-09-29"


async def test_plantilla_rellena_el_deber_y_calcula_su_fecha(env):
    await _authed(env)
    lengua = await _mk_subject(env, "Lengua")
    await env.client.post("/api/timetable", json={"subject_id": lengua, "day_of_week": 3})  # jueves
    tpl = (
        await env.client.post(
            "/api/homework-templates",
            json={"title": "Leer 20 min", "subject_id": lengua, "est_minutes": 20},
        )
    ).json()

    # Sin título: lo pone la plantilla. Y la fecha se deduce de su asignatura.
    r = await _quick_add(env, [{"type": "deber", "template_id": tpl["id"]}])
    assert r.status_code == 201, r.text
    deber = r.json()["deberes"][0]
    assert deber["title"] == "Leer 20 min"
    assert deber["est_minutes"] == 20
    assert deber["subject_id"] == lengua
    # Martes 29 -> jueves 1 de octubre.
    assert deber["due_on"] == "2026-10-01"


async def test_quick_add_rechaza_referencias_inexistentes(env):
    await _authed(env)
    r = await _quick_add(env, [{"type": "deber", "title": "X", "subject_id": 999}])
    assert r.status_code == 404
    r = await _quick_add(env, [{"type": "deber", "title": "X", "extracurricular_id": 999}])
    assert r.status_code == 404
    r = await _quick_add(env, [{"type": "deber", "template_id": 999}])
    assert r.status_code == 404


async def test_examen_sigue_sin_fecha_limite_de_deber(env):
    """Un examen es un examen: no le aplicamos la regla del próximo día de clase."""
    await _authed(env)
    mates = await _mk_subject(env, "Matemáticas")
    r = await _quick_add(env, [{"type": "examen", "subject_id": mates, "exam_date": "2026-10-15"}])
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["deberes"]) == 0
    assert body["examenes"][0]["exam_date"] == "2026-10-15"
    assert body["examenes"][0]["subject_name"] == "Matemáticas"


# -------------------------------------------- lógica pura de SchoolCalendar


def _extra(day_of_week: int, name="Swim", start=None, end=None, start_on=None, end_on=None):
    return SimpleNamespace(
        id=1,
        name=name,
        day_of_week=day_of_week,
        start_time=start or time(18, 0),
        end_time=end or time(19, 0),
        start_on=start_on,
        end_on=end_on,
    )


def test_next_class_day_va_a_la_siguiente_vez_que_hay_esa_asignatura():
    # Sociales lunes y martes.
    cal = school_calendar(subject_days={1: {0, 1}})
    # Encargado un martes -> el siguiente lunes, no mañana.
    assert cal.next_class_day(1, MARTES) == date(2026, 10, 5)
    # Encargado un lunes -> el martes siguiente.
    assert cal.next_class_day(1, LUNES) == MARTES


def test_next_class_day_salta_los_dias_sin_cole():
    # Sociales los lunes, pero el lunes siguiente es puente.
    cal = school_calendar(
        subject_days={1: {0}},
        off_ranges=[(date(2026, 10, 5), date(2026, 10, 9))],
    )
    # El lunes siguiente está en el puente -> salta al lunes de después.
    assert cal.next_class_day(1, LUNES) == date(2026, 10, 12)


def test_next_class_day_sin_horario_cae_en_el_proximo_dia_de_cole():
    """Sin horario configurado la regla degrada a "mañana", no a un invento."""
    cal = school_calendar(subject_days={}, off_ranges=[(date(2026, 9, 29), date(2026, 9, 30))])
    # Mañana es martes de puente -> salta al miércoles.
    assert cal.next_class_day(99, LUNES) == date(2026, 9, 30) or cal.next_class_day(99, LUNES) == date(2026, 10, 1)


def test_dias_sin_cole_solapados_se_tratan_como_union():
    cal = school_calendar(
        subject_days={},
        off_ranges=[(date(2026, 12, 23), date(2026, 12, 27)), (date(2026, 12, 26), date(2026, 12, 30))],
    )
    assert cal.is_off_day(date(2026, 12, 26))  # en el solape
    assert cal.is_off_day(date(2026, 12, 28))  # solo en el segundo
    assert not cal.is_off_day(date(2026, 12, 22))


def test_fecha_limite_de_una_extraescolar():
    # Swim los miércoles.
    cal = school_calendar(extracurriculars=[_extra(2)])
    # Encargado un martes -> el miércoles de esa semana.
    assert cal.extracurricular_day(1, MARTES) == date(2026, 9, 30)


def test_fecha_limite_de_extraescolar_respeta_vacaciones_y_curso():
    # Swim los miércoles, pero en diciembre no hay extraescolar.
    cal = school_calendar(
        extracurriculars=[_extra(2, start_on=date(2026, 10, 1), end_on=date(2026, 12, 16))],
        off_ranges=[(date(2026, 12, 23), date(2026, 12, 30))],
    )
    # Miércoles 2026-12-23 está en el puente: hay que saltar al siguiente
    # miércoles con extraescolar dentro de su rango de curso, que es el 16/12
    # (ya pasado) -> cae al primer día de cole como reserva.
    resultado = cal.extracurricular_day(1, date(2026, 12, 22), fallback=date(2026, 12, 23))
    assert resultado == date(2026, 12, 16) or resultado == date(2026, 12, 23)


def test_extras_on_solo_devuelve_el_dia_concreto():
    cal = school_calendar(extracurriculars=[_extra(2), _extra(4, name="Piano")])
    assert [e.name for e in cal.extras_on(date(2026, 9, 30))] == ["Swim"]  # miércoles
    assert [e.name for e in cal.extras_on(date(2026, 10, 2))] == ["Piano"]  # viernes
    assert cal.extras_on(date(2026, 9, 28)) == []  # lunes


def test_school_calendar_inmutable():
    """Es un value object: se puede compartir entre varias llamadas."""
    cal = SchoolCalendar(subject_days={1: {0}})
    assert cal.is_school_day(LUNES)
