"""Tests del motor de recurrencias.

Modelo (contrato del planteamiento):
- Familia calendario: ocurrencia diaria/nominal; se consume SOLO con completion
  del día exacto (`done_on`). Atrasadas sin completar quedan colapsadas.
  `since` (ancla/creación) acota el barrido hacia atrás.
- Familia real: cursor `rec_next_due <= hoy` → pendiente/atrasada hasta completar.
"""

from datetime import date

from app.services.engine import (
    TaskRules,
    add_interval,
    compute_next_cursor,
    is_due_on,
    next_nominal,
    nominal_dates_between,
    pending_occurrence,
    previous_nominal,
    scheduled_dates_between,
)

D = date


# ---------------------------------------------------------------- primitivas

def test_add_interval_day_week_month():
    r = TaskRules(rec_type="interval", rec_interval=2, rec_unit="day")
    assert add_interval(r, D(2026, 9, 10)) == D(2026, 9, 12)
    r = TaskRules(rec_type="interval", rec_interval=1, rec_unit="week")
    assert add_interval(r, D(2026, 9, 10)) == D(2026, 9, 17)
    r = TaskRules(rec_type="interval", rec_interval=1, rec_unit="month")
    assert add_interval(r, D(2026, 9, 30)) == D(2026, 10, 30)
    # fin de mes: relativedelta recorta
    assert add_interval(r, D(2026, 1, 31)) == D(2026, 2, 28)


def test_weekday_mask_weekly_days_due():
    # martes y jueves -> bits isoweekday 2 y 4 -> 1<<1 | 1<<3 = 10
    r = TaskRules(rec_type="weekly_days", rec_week_mask=10)
    assert is_due_on(r, D(2026, 9, 22))  # martes
    assert is_due_on(r, D(2026, 9, 24))  # jueves
    assert not is_due_on(r, D(2026, 9, 23))  # miércoles


def test_month_day_due():
    # "30" -> solo días 30 (febrero no tiene)
    r30 = TaskRules(rec_type="month_day", rec_day_of_month=30)
    assert is_due_on(r30, D(2026, 9, 30))
    assert not is_due_on(r30, D(2026, 10, 29))
    assert not is_due_on(r30, D(2026, 2, 28))  # febrero salta el 30
    # "0" -> último día del mes
    r0 = TaskRules(rec_type="month_day", rec_day_of_month=0)
    assert is_due_on(r0, D(2026, 2, 28))
    assert not is_due_on(r0, D(2026, 2, 27))
    assert is_due_on(r0, D(2026, 10, 31))
    # "31" no existe en abril
    r31 = TaskRules(rec_type="month_day", rec_day_of_month=31)
    assert not is_due_on(r31, D(2026, 4, 30))


# ---------------------------------------------------------------- calendario: pendiente

def test_daily_pending_progression():
    r = TaskRules(rec_type="daily", rec_anchor=D(2026, 9, 1))
    assert pending_occurrence(r, D(2026, 9, 1), since=D(2026, 9, 1)) == D(2026, 9, 1)
    # completado hoy (día exacto) -> ya no pende
    assert pending_occurrence(r, D(2026, 9, 1), [D(2026, 9, 1)], since=D(2026, 9, 1)) is None
    # al día siguiente pende la nueva ocurrencia
    assert pending_occurrence(r, D(2026, 9, 2), [D(2026, 9, 1)], since=D(2026, 9, 1)) == D(2026, 9, 2)


def test_weekly_days_marcar_por_adelantado_no_consume():
    # "lunes y jueves" -> bits 1 y 4 -> 1+8 = 9, desde lunes 21/09
    r = TaskRules(rec_type="weekly_days", rec_week_mask=9, rec_anchor=D(2026, 9, 21))
    mon = D(2026, 9, 21)
    thu = D(2026, 9, 24)
    # el lunes toca
    assert pending_occurrence(r, mon, since=mon) == mon
    # "adelantada": marcar el jueves (done_on=jueves) desde el lunes NO consume el lunes
    assert pending_occurrence(r, mon, [thu], since=mon) == mon
    # completado el lunes (done_on=lunes) -> lunes consumido
    assert pending_occurrence(r, mon, [mon], since=mon) is None
    # el jueves toca independientemente de haber hecho el lunes
    assert pending_occurrence(r, thu, [mon], since=mon) == thu


def test_weekly_days_atrasada_colapsada():
    # toca lunes y jueves; sin completar el lunes, el miércoles sigue "atrasado" (lunes colapsado)
    r = TaskRules(rec_type="weekly_days", rec_week_mask=9, rec_anchor=D(2026, 9, 21))
    assert pending_occurrence(r, D(2026, 9, 23), [], since=D(2026, 9, 21)) == D(2026, 9, 21)


def test_month_day_pending_avanza_por_completado_exacto():
    r = TaskRules(rec_type="month_day", rec_day_of_month=10, rec_anchor=D(2026, 10, 10))
    assert pending_occurrence(r, D(2026, 10, 10), [], since=D(2026, 10, 10)) == D(2026, 10, 10)
    # completado el día exacto 10/10 -> nada hasta el 10/11
    assert pending_occurrence(r, D(2026, 11, 9), [D(2026, 10, 10)], since=D(2026, 10, 10)) is None
    assert pending_occurrence(r, D(2026, 11, 10), [D(2026, 10, 10)], since=D(2026, 10, 10)) == D(2026, 11, 10)


# ---------------------------------------------------------------- día real: intervalo

def test_interval_cursor_avanza_con_la_fecha_real():
    r = TaskRules(rec_type="interval", rec_interval=3, rec_unit="day", rec_next_due=D(2026, 9, 1))
    assert pending_occurrence(r, D(2026, 9, 1)) == D(2026, 9, 1)
    # sin completar, el día 2 sigue atrasado (mismo cursor)
    assert pending_occurrence(r, D(2026, 9, 2)) == D(2026, 9, 1)
    # se completa el 1 -> cursor = 1+3 = 4
    assert compute_next_cursor(r, D(2026, 9, 1)) == D(2026, 9, 4)
    # y completado el día 2 (adelantado) -> cursor = 5
    assert compute_next_cursor(r, D(2026, 9, 2)) == D(2026, 9, 5)


def test_interval_pendiente_atrasado_si_no_se_completo():
    r = TaskRules(rec_type="interval", rec_interval=7, rec_unit="day", rec_next_due=D(2026, 9, 1))
    assert pending_occurrence(r, D(2026, 9, 5)) == D(2026, 9, 1)


# ---------------------------------------------------------------- rangos

def test_nominal_dates_between_daily():
    r = TaskRules(rec_type="daily")
    assert nominal_dates_between(r, D(2026, 9, 21), D(2026, 9, 23)) == [
        D(2026, 9, 21),
        D(2026, 9, 22),
        D(2026, 9, 23),
    ]


def test_scheduled_dates_between_interval():
    r = TaskRules(rec_type="interval", rec_interval=1, rec_unit="day", rec_next_due=D(2026, 9, 1))
    assert scheduled_dates_between(r, D(2026, 9, 1), D(2026, 9, 4)) == [
        D(2026, 9, 1),
        D(2026, 9, 2),
        D(2026, 9, 3),
        D(2026, 9, 4),
    ]


def test_scheduled_dates_between_month_day_jumps():
    # día 30 -> abril y mayo sí lo tienen (marzo no importa, fuera de rango)
    r = TaskRules(rec_type="month_day", rec_day_of_month=30)
    assert scheduled_dates_between(r, D(2026, 4, 1), D(2026, 5, 30)) == [D(2026, 4, 30), D(2026, 5, 30)]


def test_previous_and_next_nominal():
    r = TaskRules(rec_type="weekly_days", rec_week_mask=9)  # lun y jue
    # jueves 24 -> anterior lunes 21
    assert previous_nominal(r, D(2026, 9, 24)) == D(2026, 9, 21)
    # lunes 21 -> siguiente jueves 24
    assert next_nominal(r, D(2026, 9, 21)) == D(2026, 9, 24)

    r_month = TaskRules(rec_type="month_day", rec_day_of_month=31)
    # desde un mes no-31 hacia atrás saltamos a enero (que sí tiene 31)
    assert previous_nominal(r_month, D(2026, 4, 10)) == D(2026, 3, 31)


def test_rotation_materialized_interval_offsets():
    # rotación = tareas interval con ancla desfasada; cada ítem es independiente
    anchors = [(D(2026, 1, 1), D(2026, 2, 1)), (D(2026, 2, 1), D(2026, 3, 1)), (D(2026, 3, 1), D(2026, 4, 1))]
    for a, nxt in anchors:
        r = TaskRules(rec_type="interval", rec_interval=1, rec_unit="month", rec_next_due=a)
        assert pending_occurrence(r, a) == a
        assert compute_next_cursor(r, a) == nxt