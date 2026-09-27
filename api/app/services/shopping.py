"""Lógica de la lista de la compra (solo adulto).

El "Recomendar" (Planteamiento §2.5) es pura consulta: nombres comprados
≥2 veces en los últimos 90 días, excluyendo lo que ya está pendiente;
ordena por nº de compras (desempate: más reciente) y pre-rellena la
cantidad/unidad más frecuente del nombre.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

_SUPERFLUOUS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Nombre normalizado para agrupar/emparejar (minúsculas, sin espacios extra)."""
    return _SUPERFLUOUS.sub(" ", name.strip().lower())


def suggest(
    rows: Iterable[tuple[str, str, date]], today: date, exclude: Iterable[str], window_days: int = 90
) -> list[dict]:
    """Sugerencias de compra recurrente.

    `rows`: iterable de (name, qty, purchased_at) ya filtrado al los últimos N días.
    `exclude`: nombres normalizados que ya están pendientes (no se sugieren).
    Devuelve [{name, count, qty}] ordenado por (count desc, última compra desc).
    """
    cutoff = today - timedelta(days=window_days)
    groups: dict[str, list[tuple[str, str | None, date]]] = defaultdict(list)
    for name, qty, purchased_at in rows:
        if purchased_at is None or purchased_at < cutoff:
            continue
        groups[normalize_name(name)].append((name, qty, purchased_at))

    excluded = set(exclude)
    out: list[dict] = []
    for key, entries in groups.items():
        if key in excluded or len(entries) < 2:
            continue
        entries.sort(key=lambda e: e[2], reverse=True)
        out.append(
            {
                "name": entries[0][0],
                "qty": entries[0][1],
                "count": len(entries),
                "last_at": entries[0][2],
            }
        )

    out.sort(key=lambda e: (e["count"], e["last_at"]), reverse=True)
    return out


def most_frequent_qty(names_qty: Counter) -> str | None:
    """Cantidad/unidad más frecuente de un nombre (pre-relleno)."""
    if not names_qty:
        return None
    return names_qty.most_common(1)[0][0]