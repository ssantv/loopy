"""Tests del planner de planes de estudio (módulo colegio)."""

from datetime import date

from app.services.planner import (
    ExamPlanCfg,
    PlanItem,
    StudyTask,
    is_valid_day,
    plan_day,
    plan_progress,
    plan_span,
    resumen_complete,
    spread_daily_load,
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


# ---------------------------------------------------------------- días sin cole


def test_un_puente_no_cuenta_como_dia_de_estudio():
    assert is_valid_day(date(2026, 9, 28), True) is True
    assert is_valid_day(date(2026, 9, 28), True, {date(2026, 9, 28)}) is False


def test_el_plan_salta_las_vacaciones():
    """Examen el lunes 12/10 con el puente del 5 al 9: el repaso-final sigue
    siendo el día 11, pero el resto del plan se reparte sin tocar el puente."""
    examen = date(2026, 10, 12)
    puente = {date(2026, 10, d) for d in range(5, 10)}
    fases = {i.phase: i.date for i in plan_span(examen, _cfg(), off_days=puente)}
    assert fases["repaso-final"] == date(2026, 10, 11)
    assert date(2026, 10, 11) not in puente
    # Ningún día del plan cae dentro del puente.
    assert not (set(fases.values()) & puente)


def test_un_examen_durante_vacaciones_no_tiene_plan_dentro():
    examen = date(2026, 12, 24)
    navidad = {date(2026, 12, d) for d in range(23, 31)}
    items = plan_span(examen, _cfg(), off_days=navidad)
    assert items  # sigue habiendo plan...
    assert not ({i.date for i in items} & navidad)  # ...pero no dentro de las vacaciones


# ------------------------------------------------------- reparto de carga diaria


def _task(exam: date, day: date, phase: str, subject_id: int = 1, minutes: int = 30) -> StudyTask:
    return StudyTask(
        exam_date=exam,
        subject_id=subject_id,
        item=PlanItem(date=day, phase=phase, offset=(exam - day).days, minutes=minutes),
    )


def test_sin_colision_no_se_mueve_nada():
    """Con un solo examen el plan se queda donde está: el reparto no toca nada."""
    examen = date(2026, 9, 25)
    tasks = [_task(examen, d, "repaso-final") for d in (date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23))]
    por_dia, sin_cabida = spread_daily_load(tasks, daily_max_minutes=60)
    assert sin_cabida == []
    assert por_dia == {
        date(2026, 9, 21): [tasks[0]],
        date(2026, 9, 22): [tasks[1]],
        date(2026, 9, 23): [tasks[2]],
    }


def test_tres_examenes_el_mismo_dia_se_reparten():
    """El caso real: 3 asignaturas con sesión el mismo día = 90 min de golpe."""
    dia = date(2026, 9, 24)
    tasks = [
        _task(date(2026, 9, 25), dia, "repaso-final", subject_id=1),
        _task(date(2026, 9, 26), dia, "repaso-final", subject_id=2),
        _task(date(2026, 9, 26), dia, "repaso-final", subject_id=3),
    ]
    por_dia, sin_cabida = spread_daily_load(tasks, daily_max_minutes=60)

    assert sin_cabida == []
    # Ningún día pasa de 60 min.
    for day, items in por_dia.items():
        assert sum(i.minutes for i in items) <= 60, day
    # Con tope 60 caben dos sesiones de 30. Se quedan las dos más urgentes: el
    # examen del 25 y uno de los del 26.
    assert [t.subject_id for t in por_dia[dia]] == [1, 2]
    # La tercera se ha movido antes, no después.
    movida = [d for d in por_dia if d != dia]
    assert movida and all(d < dia for d in movida)


def test_el_repaso_final_no_se_mueve_nunca():
    """El repaso-final va pegado al examen aunque el día esté lleno."""
    dia = date(2026, 9, 24)
    relleno = [_task(date(2026, 10, 20), dia, "resumen", subject_id=9)]
    repaso = _task(date(2026, 9, 25), dia, "repaso-final", subject_id=1)
    # El relleno es de un examen más lejano, así que es menos urgente.
    por_dia, sin_cabida = spread_daily_load([*relleno, repaso], daily_max_minutes=30)
    assert sin_cabida == []
    assert por_dia[dia] == [repaso]


def test_el_reparto_no_usa_dias_sin_cole():
    dia = date(2026, 9, 24)
    tareas = [_task(date(2026, 9, 25), dia, "repaso-final", subject_id=1), _task(date(2026, 9, 26), dia, "practica", 2)]
    sin_cole = {date(2026, 9, 23), date(2026, 9, 22)}
    por_dia, sin_cabida = spread_daily_load(
        tareas, daily_max_minutes=30, is_valid=lambda d: d not in sin_cole
    )
    assert sin_cabida == []
    assert not (set(por_dia) & sin_cole)
    assert por_dia[dia][0].subject_id == 1


def test_lo_que_no_cabe_se_reporta_en_vez_de_desaparecer():
    """Con el tope muy bajo y casi sin días libres, se dice qué no cabe."""
    dia = date(2026, 9, 24)
    tareas = [_task(date(2026, 9, 25), dia, "repaso-final", subject_id=i) for i in range(3)]
    por_dia, sin_cabida = spread_daily_load(tareas, daily_max_minutes=30, max_back_days=1)
    # Caben dos: el 24 y el 23. La tercera no tiene dónde ir.
    assert len(sin_cabida) == 1
    assert sum(i.minutes for i in sin_cabida) == 30
    assert len(por_dia[dia]) == 1
    assert len(por_dia[date(2026, 9, 23)]) == 1


def test_tope_cero_o_negativo_se_trata_como_sin_tope():
    """`study_max_minutes = 0` significa "sin tope" y no "no puedes estudiar"."""
    dia = date(2026, 9, 24)
    tareas = [_task(date(2026, 9, 25), dia, "repaso-final", subject_id=i) for i in range(3)]
    por_dia, sin_cabida = spread_daily_load(tareas, daily_max_minutes=0)
    assert sin_cabida == []
    assert por_dia == {dia: tareas}
