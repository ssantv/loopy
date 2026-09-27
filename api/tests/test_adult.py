"""Tests del módulo adulto: agrupación del hogar, adelantada y compra recomendada."""

from datetime import UTC, date, datetime, timedelta

from app.services.home import group_home, next_occurrence, task_pending
from app.services.shopping import normalize_name, suggest

D = date


def _completion(done_on):
    return type("C", (), {"done_on": done_on})()


def _task(**kw):
    defaults = {
        "id": 0,
        "category": "hogar",
        "title": "tarea",
        "notes": None,
        "room_id": None,
        "due_on": None,
        "due_at": None,
        "notify": False,
        "rec_type": None,
        "rec_interval": 1,
        "rec_unit": None,
        "rec_week_mask": 0,
        "rec_day_of_month": None,
        "rec_anchor": None,
        "rec_next_due": None,
        "archived_at": None,
        "est_minutes": None,
        "last_done_on": None,
        "sort": 0,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "completions": [],
    }
    defaults.update(kw)
    return type("TaskFake", (), defaults)()


def _room(id, name="Sala", color="#aabbcc"):
    return type("R", (), {"id": id, "name": name, "color": color})()


# ---------------------------------------------------------------- hogar

def test_puntual_pending_atrasada():
    t = _task(rec_type=None, due_on=D(2026, 9, 19))
    assert task_pending(t, D(2026, 9, 20)) == D(2026, 9, 19)
    t2 = _task(rec_type=None, due_on=D(2026, 9, 20))
    assert task_pending(t2, D(2026, 9, 20)) == D(2026, 9, 20)
    t3 = _task(rec_type=None, due_on=D(2026, 9, 21))
    assert task_pending(t3, D(2026, 9, 20)) is None


def test_puntual_hecha_no_aparece():
    t = _task(rec_type=None, due_on=D(2026, 9, 20))
    t2 = _task(id=1, rec_type=None, due_on=D(2026, 9, 20))
    t2.completions = [_completion(D(2026, 9, 20))]
    assert task_pending(t, D(2026, 9, 20)) == D(2026, 9, 20)
    assert task_pending(t2, D(2026, 9, 20)) is None


def test_recurrent_pending_y_next():
    weekly = _task(rec_type="weekly_days", rec_week_mask=1, rec_anchor=D(2026, 9, 14))  # lunes
    # 2026-09-20 es domingo → el lunes 14 no está completado y es la última atrasada
    assert task_pending(weekly, D(2026, 9, 20)) == D(2026, 9, 14)
    weekly2 = _task(id=2, rec_type="weekly_days", rec_week_mask=1, rec_anchor=D(2026, 9, 14))
    weekly2.completions = [_completion(D(2026, 9, 14))]
    # lunes hecho → nada pendiente hoy, lo siguiente toca el lunes 21
    assert task_pending(weekly2, D(2026, 9, 20)) is None
    assert next_occurrence(weekly2, D(2026, 9, 20)) == D(2026, 9, 21)


def test_interval_next():
    interval = _task(id=3, rec_type="interval", rec_interval=3, rec_unit="day", rec_next_due=D(2026, 9, 25))
    assert next_occurrence(interval, D(2026, 9, 20)) == D(2026, 9, 25)
    interval2 = _task(id=4, rec_type="interval", rec_interval=3, rec_unit="day", rec_next_due=D(2026, 9, 19))
    assert next_occurrence(interval2, D(2026, 9, 20)) is None  # atrasada → pendiente, no adelantada


def test_puntual_futura_adelantada():
    t = _task(rec_type=None, due_on=D(2026, 9, 22))
    assert next_occurrence(t, D(2026, 9, 20)) == D(2026, 9, 22)


def test_group_home_por_habitacion():
    today = D(2026, 9, 20)
    sala = _room(1)
    cocina = _room(2, "Cocina")
    pend_sala = _task(id=10, category="hogar", room_id=1, due_on=today)
    ahead_sala = _task(
        id=11, category="hogar", room_id=1, rec_type="weekly_days", rec_week_mask=1, rec_anchor=D(2026, 9, 7)
    )
    # dos lunes hechos (ancla y siguiente): nada pendiente, lo próximo es el lunes 21
    ahead_sala.completions = [_completion(D(2026, 9, 7)), _completion(D(2026, 9, 14))]
    general = _task(id=12, category="general", due_on=today)  # sin habitación
    puntual_fut = _task(id=13, category="puntual", due_on=D(2026, 9, 25))
    colegio = _task(id=14, category="colegio-deberes", due_on=today)  # fuera del hogar adulto

    out = group_home([pend_sala, ahead_sala, general, puntual_fut, colegio], [sala, cocina], today)
    assert len(out["rooms"]) == 2
    assert [i["id"] for i in out["rooms"][0]["pending"]] == [10]
    assert [i["id"] for i in out["rooms"][0]["ahead"]] == [11]
    assert out["rooms"][0]["ahead"][0]["next_on"] == D(2026, 9, 21)
    assert [i["id"] for i in out["no_room"]["pending"]] == [12]
    assert [i["id"] for i in out["no_room"]["ahead"]] == [13]
    # las habitaciones vacías aparecen con listas vacías
    assert out["rooms"][1]["pending"] == [] and out["rooms"][1]["ahead"] == []


def test_normalize_name():
    assert normalize_name("  Leche   Semidesnatada ") == "leche semidesnatada"
    assert normalize_name("LECHE") == "leche"


def test_suggest_excluye_pendientes_y_agrupa():
    today = D(2026, 9, 20)
    rows = [
        ("Leche", "1 L", today - timedelta(days=3)),
        (" leche ", "2 L", today - timedelta(days=40)),
        ("Yogures", "6", today - timedelta(days=5)),
        ("Yogures", "6", today - timedelta(days=60)),
        ("Pan de molde", "1", today - timedelta(days=2)),  # solo 1 compra → no sugiere
    ]
    out = suggest(rows, today, exclude=["leche"])
    names = [s["name"] for s in out]
    assert names == ["Yogures"]  # leche excluida (pendiente), pan <2 compras
    assert out[0]["qty"] == "6"
    assert out[0]["count"] == 2


def test_suggest_no_sale_por_fuera_de_ventana():
    today = D(2026, 9, 20)
    rows = [
        ("Leche", "1 L", today - timedelta(days=100)),
        ("Leche", "2 L", today - timedelta(days=95)),
    ]
    assert suggest(rows, today, exclude=[]) == []