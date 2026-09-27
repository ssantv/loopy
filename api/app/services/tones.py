"""Tonos de notificación del perfil niño.

El tono se sugiere por edad (`tone_for_age`) y las plantillas de cada evento
viven en código (`EVENT_TEMPLATES`), tal como manda el planteamiento: sin
migraciones para afinarlas.

Regla transversal: **cero apelativos cariñosos** ("cielo", "bonito",
"cariño") en ningún tono; la calidez es lenguaje de misión/exclamación, no
motes.
"""

from __future__ import annotations

# Orden legible de tonos (edad de menor a mayor).
TONES: tuple[str, ...] = ("jugueton", "cercano", "directo-amistoso", "directo")

# Default (sin fecha de nacimiento o adulto)
DEFAULT_TONE = "cercano"


def tone_for_age(age: int | None) -> str:
    """Tono sugerido según la tabla de Planteamiento §4.

    | Edad        | Tono             |
    |-------------|------------------|
    | <6 y 6–8    | jugueton         |
    | 9–11        | cercano          |
    | 12–14       | directo-amistoso |
    | 15+         | directo          |
    """
    if age is None:
        return DEFAULT_TONE
    if age < 9:
        return "jugueton"
    if age <= 11:
        return "cercano"
    if age <= 14:
        return "directo-amistoso"
    return "directo"


# Plantillas por evento y tono. El contrato solo define "checkin" por ahora;
# otros eventos (reminder/summary) se sumarán cuando se implementen.
EVENT_TEMPLATES: dict[str, dict[str, str]] = {
    "checkin": {
        "jugueton": "¡Misión del día! ¿Hay tareas nuevas? 🔍",
        "cercano": "¡Hola! ¿Te han mandado tareas nuevas hoy? Cuéntamelas",
        "directo-amistoso": "Tareas nuevas de hoy, ¿qué te han puesto?",
        "directo": "¿Alguna tarea nueva hoy?",
    },
}


def template(event: str, tone: str | None = None) -> str:
    """Texto del push para `event` en `tone` (por defecto el tono del usuario o el default)."""
    per_tone = EVENT_TEMPLATES.get(event, {})
    text = per_tone.get(tone or "") or per_tone.get(DEFAULT_TONE) or ""
    return text