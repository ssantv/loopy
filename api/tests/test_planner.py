"""Tests del planner de planes de estudio (módulo colegio)."""

from datetime import date

from app.services.planner import (
    ExamPlanCfg,
    PlanItem,
    is_valid_day,
    plan_day,
    plan_progress,
    plan_span,
    resumen_complete,
)


def _cfg(**kw) -> ExamPlanCfg:
    return ExamPlanCfg(**kw)


def _phases(exam: date, cfg: ExamPlanCfg) -> dict[str, date]:
    """Mapa fase -> fecha a partir del plan generado."""

    items = plan_span(exam, cfg)
    return {item.phase: item.date for item in items}


# ---------------------------------------------------------- ejemplo del contrato

def test_ejemplo_lengua_1_1_1_1():
    """Ejemplo del Planteamiento: (1,1,1,1) examen 25/09 -> resumen=21,
    estudio=22, practica=23, repaso-final=24."""
    d = date(2026, 9, 25)
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=1, days_repaso=1)
    got = _phases(d, cfg)
    assert got == {
        "resumen": date(2026, 9, 21),
        "estudio": date(2026, 9, 22),
        "practica": date(2026, 9, 23),
        "repaso-final": date(2026, 9, 24),
    }


def test_fases_con_r_3():
    """Con repaso=3, los 3 últimos días antes del examen son repaso (final)."""
    d = date(2026, 10, 5)
    cfg = _cfg(days_resumen=1, days_estudio=2, days_practica=2, days_repaso=3)
    got = _phases(d, cfg)
    assert got["repaso-final"] == date(2026, 10, 4)
    assert got["repaso"] == date(2026, 10, 3)
    assert got["practica"] == date(2026, 10, 1)
    assert got["estudio"] == date(2026, 9, 29)
    assert got["resumen"] == date(2026, 9, 27)


def test_offset_es_continua_desde_D_menos_1():
    """El offset camina hacia atrás día a día empezando en D-1."""
    d = date(2026, 9, 25)
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=1, days_repaso=1)
    assert plan_day(d, cfg, date(2026, 9, 24)).offset == 1
    assert plan_day(d, cfg, date(2026, 9, 23)).offset == 2
    assert plan_day(d, cfg, date(2026, 9, 22)).offset == 3
    assert plan_day(d, cfg, date(2026, 9, 21)).offset == 4


def test_dia_del_examen_no_tiene_plan():
    d = date(2026, 9, 25)
    cfg = _cfg()
    assert plan_day(d, cfg, d) is None


def test_fuera_de_ventana_no_tiene_plan():
    d = date(2026, 9, 25)
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=1, days_repaso=1)
    assert plan_day(d, cfg, date(2026, 9, 20)) is None


# ---------------------------------------------------------------- compresión

def test_compresion_si_examen_cerca():
    """Si hoy está dentro del plan pero no alcanza para todas las fases,
    solo aparecen las más cercanas al examen (hacia atrás desde hoy)."""
    d = date(2026, 9, 25)
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=1, days_repaso=1)
    got = plan_span(d, cfg, start=date(2026, 9, 22))
    assert [i.phase for i in got] == ["estudio", "practica", "repaso-final"]


def test_plan_span_acota_por_fechas():
    d = date(2026, 9, 25)
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=1, days_repaso=1)
    got = plan_span(d, cfg, start=date(2026, 9, 23), end=date(2026, 9, 24))
    assert [i.phase for i in got] == ["practica", "repaso-final"]


# ---------------------------------------------------------- fines de semana

def test_include_weekends_default_true_cuenta_sabado():
    d = date(2026, 9, 28)  # lunes
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=1, days_repaso=1)
    assert plan_day(d, cfg, date(2026, 9, 26)) is not None  # sábado
    assert plan_day(d, cfg, date(2026, 9, 27)) is not None  # domingo
    assert plan_day(d, cfg, date(2026, 9, 27)).offset == 1  # dom = D-1
    assert plan_day(d, cfg, date(2026, 9, 26)).offset == 2
    assert plan_day(d, cfg, date(2026, 9, 25)).offset == 3


def test_include_weekends_false_salta_fin_de_semana():
    """Examen lunes 28/09 sin fines de semana: 27 es domingo (sin plan) y
    X=1 se asigna al viernes 25 (repaso-final), X=2 al jueves 24."""
    d = date(2026, 9, 28)  # lunes
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=1, days_repaso=1, include_weekends=False)
    assert is_valid_day(date(2026, 9, 26), False) is False
    assert is_valid_day(date(2026, 9, 27), False) is False
    got = _phases(d, cfg)
    assert got == {
        "resumen": date(2026, 9, 22),
        "estudio": date(2026, 9, 23),
        "practica": date(2026, 9, 24),
        "repaso-final": date(2026, 9, 25),
    }


# -------------------------------------------------------------- resumen adelantado

def test_resumen_completo_omite_fase_resumen():
    """Si resumen_total_pages=10 y done=10, la fase resumen no aparece."""
    d = date(2026, 9, 25)
    cfg = _cfg(
        days_resumen=1,
        days_estudio=1,
        days_practica=1,
        days_repaso=1,
        resumen_total_pages=10,
    )
    assert resumen_complete(cfg, done_pages=10) is True
    got = {item.phase: item.date for item in plan_span(d, cfg, resumen_done_pages=10)}
    assert "resumen" not in got
    assert got["estudio"] == date(2026, 9, 22)
    assert got["practica"] == date(2026, 9, 23)
    assert got["repaso-final"] == date(2026, 9, 24)


def test_resumen_parcial_mantiene_fase():
    d = date(2026, 9, 25)
    cfg = _cfg(
        days_resumen=1,
        days_estudio=1,
        days_practica=1,
        days_repaso=1,
        resumen_total_pages=10,
    )
    assert resumen_complete(cfg, done_pages=4) is False
    got = plan_span(d, cfg, resumen_done_pages=4)
    assert {i.phase for i in got} == {"resumen", "estudio", "practica", "repaso-final"}


def test_resumen_total_nulo_no_omite_pese_a_done_pages():
    """resumen_total_pages NULL => no se puede decir que está completo."""
    d = date(2026, 9, 25)
    cfg = _cfg(resumen_total_pages=None)
    assert resumen_complete(cfg, done_pages=50) is False
    got = plan_span(d, cfg, resumen_done_pages=99)
    assert any(i.phase == "resumen" for i in got)


def test_sin_practica():
    """P=0 comprimido: práctica no aparece."""
    d = date(2026, 9, 25)
    cfg = _cfg(days_resumen=1, days_estudio=1, days_practica=0, days_repaso=1)
    got = _phases(d, cfg)
    assert got == {
        "resumen": date(2026, 9, 22),
        "estudio": date(2026, 9, 23),
        "repaso-final": date(2026, 9, 24),
    }


# ------------------------------------------------------------------ helpers

def test_plan_item_es_dataclass_ordenada():
    items = plan_span(date(2026, 9, 25), _cfg())
    assert all(isinstance(i, PlanItem) for i in items)
    offsets = [i.offset for i in items]
    assert offsets == sorted(offsets, reverse=True)  # más lejano primero


# ------------------------------------------------- minutos -> sesiones -> fases

def test_el_ejemplo_documentado_se_sigue_cumpliendo():
    """120min / 30min = 4 sesiones, repartidas 1 por fase: el ejemplo de §2.4."""
    cfg = ExamPlanCfg.from_minutes(prep_minutes=120, session_minutes=30)
    assert (cfg.days_resumen, cfg.days_estudio, cfg.days_practica, cfg.days_repaso) == (1, 1, 1, 1)


def test_mas_minutos_mas_sesiones():
    cfg = ExamPlanCfg.from_minutes(prep_minutes=180, session_minutes=30)
    assert cfg.total_sessions == 6
    assert sum((cfg.days_resumen, cfg.days_estudio, cfg.days_practica, cfg.days_repaso)) == 6


def test_el_sobrante_va_a_las_fases_mas_tempranas():
    """6 sesiones entre 4 fases = 1,5 cada una: el resto se lleva resumen y estudio."""
    cfg = ExamPlanCfg.from_minutes(prep_minutes=180, session_minutes=30)
    assert (cfg.days_resumen, cfg.days_estudio, cfg.days_practica, cfg.days_repaso) == (2, 2, 1, 1)


def test_una_fase_con_peso_cero_se_queda_sin_dias():
    """'Practica a 0 si la asignatura no la necesita'."""
    cfg = ExamPlanCfg.from_minutes(prep_minutes=180, session_minutes=30, weights=(1, 1, 0, 1))
    assert cfg.days_practica == 0
    assert cfg.total_sessions == 6


def test_pesos_desiguales_se_respetan():
    """Resumen pesa el doble que el resto: se lleva mas de la mitad de las sesiones."""
    cfg = ExamPlanCfg.from_minutes(prep_minutes=200, session_minutes=30, weights=(2, 1, 1, 1))
    assert (cfg.days_resumen, cfg.days_estudio, cfg.days_practica, cfg.days_repaso) == (3, 2, 1, 1)
    assert cfg.total_sessions == 7


def test_un_tiempo_muy_corto_da_una_sesion():
    cfg = ExamPlanCfg.from_minutes(prep_minutes=10, session_minutes=30)
    assert cfg.total_sessions == 1


def test_tiempo_cero_da_una_sesion():
    """Nunca un examen sin plan, ni aunque el tiempo sea 0."""
    cfg = ExamPlanCfg.from_minutes(prep_minutes=0, session_minutes=30)
    assert cfg.total_sessions == 1
    assert sum((cfg.days_resumen, cfg.days_estudio, cfg.days_practica, cfg.days_repaso)) == 1


def test_todos_los_pesos_cero_reparte_equitativamente():
    cfg = ExamPlanCfg.from_minutes(prep_minutes=120, session_minutes=30, weights=(0, 0, 0, 0))
    assert sum((cfg.days_resumen, cfg.days_estudio, cfg.days_practica, cfg.days_repaso)) == 4


def test_el_plan_genera_un_item_por_sesion():
    cfg = ExamPlanCfg.from_minutes(prep_minutes=180, session_minutes=30)
    items = plan_span(date(2026, 9, 25), cfg)
    assert len(items) == 6
    assert all(i.minutes == 30 for i in items)


def test_progress_dice_los_minutos_que_quedan():
    cfg = ExamPlanCfg.from_minutes(prep_minutes=180, session_minutes=30)
    items = plan_span(date(2026, 9, 25), cfg)

    p = plan_progress(date(2026, 9, 25), cfg, done_dates={items[0].date}, today=items[0].date)
    assert p["total_sessions"] == 6
    assert p["total_minutes"] == 180
    assert p["done_sessions"] == 1
    assert p["pending_sessions"] == 5
    assert p["pending_minutes"] == 150


def test_progress_no_cuenta_como_hecho_lo_que_ya_esta_en_el_pasado():
    """Los días que quedaron atrás y no se hicieron no son 'hechos' ni 'pendientes'."""
    cfg = ExamPlanCfg.from_minutes(prep_minutes=180, session_minutes=30)
    items = plan_span(date(2026, 9, 25), cfg)
    hoy = items[-1].date  # el día más cercano al examen

    p = plan_progress(date(2026, 9, 25), cfg, done_dates=set(), today=hoy)
    assert p["done_sessions"] == 0
    assert p["pending_sessions"] == 1


def test_progress_cuenta_el_resumen_terminado():
    """Resumen completo = no cuenta ni como total ni como pendiente."""
    cfg = ExamPlanCfg.from_minutes(prep_minutes=120, session_minutes=30, resumen_total_pages=3)
    p = plan_progress(date(2026, 9, 25), cfg, done_dates=set(), today=date(2026, 9, 24), resumen_done_pages=3)
    assert p["total_sessions"] == 3  # 4 sesiones menos la de resumen