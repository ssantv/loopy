"""El "hoy" de cada usuario.

Todo lo que depende de un día (qué toca hoy, qué está atrasado, la carga del
día) tiene que usar la fecha local del niño, no la del servidor: en Chile pueden
ser 8 horas de diferencia y cambiaría de día exactamente cuando no debe.

La tabla de zona horaria no siempre entra en `tzdata` de Windows, así que un
`ZoneInfo` inválido degrada a UTC en lugar de romper la pantalla.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.models.user import User


def hoy(user: User) -> date:
    """Fecha local del usuario."""
    try:
        return datetime.now(ZoneInfo(user.timezone)).date()
    except Exception:
        return datetime.now(UTC).date()