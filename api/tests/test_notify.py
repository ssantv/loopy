"""Tests del scheduler de notificaciones: matemática de planificación y payloads."""

from datetime import UTC, datetime, time

from app.services.notify import (
    build_payload,
    first_masked_day,
    next_masked_dt,
    next_summary_dt,
    next_task_reminder_local,
    summarize_day,
    tz_of,
)
from app.services.tones import template as tone_template

TZ = tz_of(type("U", (), {"timezone": "Europe/Madrid"})())


def _user(tone="cercano"):
    return type("U", (), {"id": 1, "profile_type": "adult", "notification_tone": tone})()


def _task(**kw):
    defaults = {
        "id": 0,
        "title": "Tarea",
        "notes": None,
        "due_on": None,
        "due_at": None,
        "notify": True,
        "rec_type": None,
        "rec_interval": 1,
        "rec_unit": None,
        "rec_week_mask": 0,
        "rec_day_of_month": None,
        "rec_anchor": None,
        "rec_next_due": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "completions": [],
    }
    defaults.update(kw)
    return type("TaskFake", (), defaults)()


def _c(done_on):
    return type("C", (), {"done_on": done_on})()


# ---------------------------------------------------------------- días con máscara

def test_first_masked_day_basico():
    # 2026-09-20 es domingo (6). El primer lunes (bit 0) es el 21.
    assert first_masked_day(datetime(2026, 9, 20).date(), 1) == datetime(2026, 9, 21).date()
    assert first_masked_day(datetime(2026, 9, 20).date(), 1 << 6) == datetime(2026, 9, 20).date()


def test_next_masked_dt_hoy_no_pasado():
    now = datetime(2026, 9, 20, 8, 0, tzinfo=TZ)  # domingo 8:00
    nxt = next_masked_dt(1 << 6, time(9, 0), TZ, now)  # domingos 9:00
    assert nxt.date() == now.date()
    assert nxt.hour == 9


def test_next_masked_dt_salta_si_hora_pasada():
    now = datetime(2026, 9, 20, 20, 0, tzinfo=TZ)
    nxt = next_masked_dt(1 << 6, time(9, 0), TZ, now)
    assert nxt.date() == datetime(2026, 9, 27).date()  # domingo siguiente


def test_next_masked_dt_dia_no_en_mascara():
    now = datetime(2026, 9, 20, 8, 0, tzinfo=TZ)  # domingo
    nxt = next_masked_dt(1, time(9, 0), TZ, now)  # solo lunes
    assert nxt.date() == datetime(2026, 9, 21).date()


# ---------------------------------------------------------------- resumen con excepciones

def test_next_summary_dt_skip():
    now = datetime(2026, 9, 20, 8, 0, tzinfo=TZ)  # domingo en máscara
    exc = {datetime(2026, 9, 20).date(): "skip"}  # hoy se salta
    nxt = next_summary_dt(1 << 6, time(9, 0), TZ, now, exc)
    assert nxt.date() == datetime(2026, 9, 27).date()


def test_next_summary_dt_add_fuera_de_mascara():
    now = datetime(2026, 9, 21, 8, 0, tzinfo=TZ)  # lunes, máscara solo domingo
    exc = {datetime(2026, 9, 21).date(): "add"}
    nxt = next_summary_dt(1 << 6, time(9, 0), TZ, now, exc)
    assert nxt.date() == datetime(2026, 9, 21).date()  # el add gana al no-máscara


def test_next_summary_dt_sin_excepciones_salta_al_domingo():
    now = datetime(2026, 9, 21, 8, 0, tzinfo=TZ)
    nxt = next_summary_dt(1 << 6, time(9, 0), TZ, now, {})
    assert nxt.date() == datetime(2026, 9, 27).date()


# ---------------------------------------------------------------- recordatorio de tarea

def test_reminder_puntual_hoy_hora_pasada_nada():
    task = _task(rec_type=None, due_on=datetime(2026, 9, 20).date())
    now = datetime(2026, 9, 20, 9, 0, tzinfo=TZ)
    # due_at None → sin hora no se avisa
    assert next_task_reminder_local(task, now) is None


def test_reminder_puntual_hoy_tras_la_hora():
    task = _task(rec_type=None, due_on=datetime(2026, 9, 20).date(), due_at=datetime(2026, 9, 20, 21, 0, tzinfo=TZ))
    now = datetime(2026, 9, 20, 9, 0, tzinfo=TZ)
    nxt = next_task_reminder_local(task, now)
    assert nxt == datetime(2026, 9, 20, 21, 0, tzinfo=TZ)


def test_reminder_puntual_ya_pasado_se_omite():
    task = _task(rec_type=None, due_on=datetime(2026, 9, 20).date(), due_at=datetime(2026, 9, 20, 21, 0, tzinfo=TZ))
    now = datetime(2026, 9, 20, 22, 0, tzinfo=TZ)
    assert next_task_reminder_local(task, now) is None


def test_reminder_recurrente_pendiente_hoy():
    task = _task(
        rec_type="daily",
        rec_anchor=datetime(2026, 9, 14).date(),
        due_at=datetime(2026, 9, 20, 21, 0, tzinfo=TZ),
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=TZ)  # la de hoy sigue pendiente → avisa hoy a las 21
    assert next_task_reminder_local(task, now) == datetime(2026, 9, 20, 21, 0, tzinfo=TZ)


def test_reminder_recurrente_hecha_salta_al_proximo_dia():
    task = _task(
        rec_type="daily",
        rec_anchor=datetime(2026, 9, 14).date(),
        due_at=datetime(2026, 9, 20, 21, 0, tzinfo=TZ),
    )
    task.completions = [_c(datetime(2026, 9, 20).date())]
    now = datetime(2026, 9, 20, 9, 0, tzinfo=TZ)
    assert next_task_reminder_local(task, now) == datetime(2026, 9, 21, 21, 0, tzinfo=TZ)


def test_reminder_sin_notify_no_avisa():
    task = _task(
        rec_type=None,
        due_on=datetime(2026, 9, 20).date(),
        due_at=datetime(2026, 9, 20, 21, 0, tzinfo=TZ),
        notify=False,
    )
    now = datetime(2026, 9, 20, 9, 0, tzinfo=TZ)
    assert next_task_reminder_local(task, now) is None


# ---------------------------------------------------------------- resumen de texto

def _shop(purchased=False, name="Leche"):
    return type("S", (), {"name": name, "purchased": purchased})()


def test_summarize_day_combina_pendientes_atrasadas_y_compra():
    hoy = datetime(2026, 9, 20).date()
    tasks = [
        _task(id=1, title="Lengua", rec_type=None, due_on=hoy),
        _task(id=2, title="Matemáticas", rec_type=None, due_on=hoy),
        _task(id=3, title="Dientes", rec_type=None, due_on=datetime(2026, 9, 19).date()),
    ]
    text = summarize_day(tasks, [_shop(), _shop(purchased=True)], hoy)
    assert "2 tareas para hoy" in text
    assert "1 atrasadas" in text
    assert "1 en la compra" in text


def test_summarize_day_una_sola_tarea_dice_cual():
    # Con una sola cosa pendiente, el recuento no ayuda a nadie: el nombre sí.
    hoy = datetime(2026, 9, 20).date()
    text = summarize_day([_task(id=1, title="Sacar basura", rec_type=None, due_on=hoy)], [], hoy)
    assert "1 tarea: Sacar basura" in text
    assert "tareas para hoy" not in text


def test_summarize_day_vacio():
    text = summarize_day([], [], datetime(2026, 9, 20).date())
    assert "Nada pendiente" in text


def test_summarize_day_cabe_en_un_banner():
    # Un push de móvil se lee en dos segundos: el texto no puede crecer con el
    # número de tareas ni con la longitud de los títulos.
    hoy = datetime(2026, 9, 20).date()
    tasks = [_task(id=i, title="Tarea " + "x" * 40, rec_type=None, due_on=hoy) for i in range(40)]
    tasks += [_task(id=100 + i, title="Atrasada", rec_type=None, due_on=datetime(2026, 9, 1).date()) for i in range(12)]
    text = summarize_day(tasks, [_shop(), _shop(name="Pan")], hoy)
    assert len(text) < 90
    assert "40 tareas" in text
    assert "12 atrasadas" in text


# ---------------------------------------------------------------- payloads

def test_payload_checkin_usa_tono():
    p = build_payload(_user("jugueton"), "checkin", {})
    assert p["title"] == "Check-in"
    assert p["body"] == tone_template("checkin", "jugueton")


def test_payload_reminder_con_notas():
    p = build_payload(_user(), "reminder", {"title": "Sacar basura", "notes": "Antes de las 22", "url": "/"})
    assert p["title"] == "Sacar basura"
    assert p["body"] == "Antes de las 22"
    assert p["url"] == "/"


def test_payload_test():
    p = build_payload(_user(), "test", {"text": "Hola", "url": "/"})
    assert "Hola" in p["body"]
    assert p["title"] == "Loopy"


def test_payload_summary_con_dia():
    p = build_payload(_user(), "summary", {"day": "2026-09-20", "url": "/"})
    assert "2026-09-20" in p["body"]


# pequeño guard para linters: timedelta está disponible si se usa para backoff fijo
def _backoff_len():
    from app.config import settings

    return len(settings.push_backoff)


def test_backoff_configurado():
    assert _backoff_len() == 5