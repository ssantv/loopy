"""Uniones de tramos horarios.

El helper es tonto a propósito, así que lo que se prueba aquí es que hace lo que dice
en los casos raros: un tramo contenido en otro, dos tramos que solo se tocan, un
`fin` antes del `inicio` por datos corruptos y el orden en que llegan.
"""

from __future__ import annotations

from app.services.tramos import minutos, une


def test_horas_vacias():
    assert minutos([]) == 0


def test_un_solo_tramo():
    assert minutos([(1020, 1080)]) == 60


def test_tramos_separados_suman():
    # 17:00-18:00 y 20:00-21:00: dos huecos distintos, 120 minutos.
    assert minutos([(1020, 1080), (1200, 1260)]) == 120


def test_tramos_que_se_pisan_no_repite():
    # 17:00-18:00 y 17:30-18:30 se solapan 30 min: 90, no 120.
    assert minutos([(1020, 1080), (1050, 1110)]) == 90


def test_tramos_iguales_no_repite():
    # Los dos hermanos en la misma actividad: una hora, no dos.
    assert minutos([(1020, 1080), (1020, 1080)]) == 60


def test_un_tramo_dentro_de_otro():
    assert minutos([(1020, 1200), (1050, 1080)]) == 180


def test_tramos_que_se_tocan():
    # 17:00-18:00 y 18:00-19:00 son 120 minutos seguidos: no hay hueco entre medias.
    assert minutos([(1020, 1080), (1080, 1140)]) == 120


def test_tramos_encadenados():
    # Tres trozos pegados: 180 minutos, no 60 + 60 + 60 contados tres veces.
    assert minutos([(600, 660), (660, 720), (720, 780)]) == 180


def test_tramos_anidados_en_el_medio():
    # El central está dentro de los otros dos: la unión sigue siendo la misma.
    assert minutos([(600, 720), (660, 690), (630, 750)]) == 150


def test_un_tramo_invertido_no_cuenta():
    # `end_time` antes de `start_time` es dato corrupto y no debe sumar nada.
    assert minutos([(1080, 1020)]) == 0


def test_un_tramo_invertido_no_arrastra_a_los_demas():
    assert minutos([(1020, 1080), (1200, 1140), (1200, 1260)]) == 120


def test_no_depende_del_orden_de_entrada():
    assert minutos([(1200, 1260), (1020, 1080)]) == minutos([(1020, 1080), (1200, 1260)])


def test_une_devuelve_los_tramos_fundidos():
    assert une([(1020, 1080), (1050, 1110), (1300, 1320)]) == [(1020, 1110), (1300, 1320)]


def test_une_admite_un_generador():
    # Se le pasa un generador porque en `day.py` los tramos se construyen al vuelo.
    assert minutos((ini, fin) for ini, fin in [(1020, 1080), (1050, 1110)]) == 90


def test_une_de_una_sola_pasada_une_los_que_llegan_desordenados():
    # El de en medio se solapa con el primero, y llega el último: aun así se une.
    assert une([(1200, 1260), (1020, 1080), (1050, 1170)]) == [(1020, 1170), (1200, 1260)]


def test_une_funde_una_cadena_sin_dejar_dos_pasadas():
    # 1050-1170 y 1170-1260 se tocan: los tres tramos son un solo bloque.
    assert une([(1020, 1080), (1050, 1170), (1170, 1260)]) == [(1020, 1260)]