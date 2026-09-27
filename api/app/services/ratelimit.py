"""Limitador de intentos en memoria con ventana deslizante.

Protege el login (y otros endpoints sensibles) contra fuerza bruta: se cuentan
los **intentos fallidos** por clave y, al superar el máximo, se bloquea durante
la ventana. Un login correcto limpia el contador de esa clave.

Notas de diseño:
- Es deliberadamente **en memoria**: no requiere migraciones ni tabla nueva. La
  API corre con un único worker de uvicorn (ver `deploy/Dockerfile.api`), así
  que el estado es consistente. Si algún día se usan varios workers o varias
  réplicas, habría que mover este estado a Postgres/Redis.
- Sólo cuenta fallos: un usuario legítimo que se equivoca tres veces y luego
  entra bien no queda penalizado.
- Las entradas caducadas se podan para que el diccionario no crezca sin límite.
"""

from __future__ import annotations

import math
import time
from collections import deque
from threading import Lock


class SlidingWindowLimiter:
    """Permite `limit` fallos por clave y ventana; bloquea hasta que caducan."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, int(limit))
        self.window = max(1, int(window_seconds))
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Segundos que faltan para dejar de estar bloqueado (0 si no lo está)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._live(key, now)
            if len(hits) < self.limit:
                return 0
            # La ventana se libera cuando caduca el intento más antiguo.
            return max(1, math.ceil(hits[0] + self.window - now))

    def record_failure(self, key: str, now: float | None = None) -> None:
        """Suma un intento fallido a la clave."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._live(key, now)
            hits.append(now)

    def reset(self, key: str) -> None:
        """Olvida los fallos de la clave (login correcto o registro)."""
        with self._lock:
            self._hits.pop(key, None)

    def attempts(self, key: str, now: float | None = None) -> int:
        """Fallos vigentes de la clave (solo para tests/diagnóstico)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            return len(self._live(key, now))

    def _live(self, key: str, now: float) -> deque[float]:
        """Devuelve la deque ya podada de la clave (llamar con el lock cogido)."""
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def prune(self, now: float | None = None) -> None:
        """Borra claves totalmente caducadas (llamado desde el scheduler)."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
                del self._hits[key]
