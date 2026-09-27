"""Tests del servicio de tonos del perfil niño."""

from app.services.tones import (
    DEFAULT_TONE,
    EVENT_TEMPLATES,
    TONES,
    template,
    tone_for_age,
)

FORBIDDEN_APELATIVOS = ("cielo", "bonito", "cariño", "carino", "nene", "nena")


def test_tono_por_edad_fronteras():
    assert tone_for_age(None) == DEFAULT_TONE
    assert tone_for_age(5) == "jugueton"  # <6
    assert tone_for_age(8) == "jugueton"  # 6-8
    assert tone_for_age(9) == "cercano"  # 9-11
    assert tone_for_age(11) == "cercano"
    assert tone_for_age(12) == "directo-amistoso"  # 12-14
    assert tone_for_age(14) == "directo-amistoso"
    assert tone_for_age(15) == "directo"  # 15+
    assert tone_for_age(99) == "directo"


def test_todos_los_tonos_cubren_el_checkin():
    assert set(EVENT_TEMPLATES["checkin"]) == set(TONES)


def test_template_checkin_por_tono():
    assert template("checkin", "jugueton") == "¡Misión del día! ¿Hay tareas nuevas? 🔍"
    assert template("checkin", "cercano") == "¡Hola! ¿Te han mandado tareas nuevas hoy? Cuéntamelas"
    assert template("checkin", "directo-amistoso") == "Tareas nuevas de hoy, ¿qué te han puesto?"
    assert template("checkin", "directo") == "¿Alguna tarea nueva hoy?"


def test_template_default_si_tono_desconocido():
    # Tono desconocido → vuelve al default (cercano).
    assert template("checkin", "desconocido") == template("checkin", DEFAULT_TONE)


def test_template_evento_desconocido_vacio():
    assert template("reminder") == ""


def test_cero_apelativos_carinosos():
    """Regla transversal: cero apelativos cariñosos en ningún tono."""
    for event, per_tone in EVENT_TEMPLATES.items():
        for tone, text in per_tone.items():
            lowered = text.lower()
            assert not any(word in lowered for word in FORBIDDEN_APELATIVOS), (
                f"Plantilla {event}/{tone} usa un apelativo cariñoso: {text!r}"
            )