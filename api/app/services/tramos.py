"""Uniones de tramos horarios.

Este es el helper que evita el error clásico de "sumar dos cosas que se pisan": si
hay una cita de 10:00 a 12:00 y otra de 11:00 a 13:00, el día está ocupado **tres**
horas, no cuatro. Sumando salen 240 minutos y se le roban 60 al tiempo de estudio,
justo en los días más cargados, que son los que peor lo pasan.

La unión importa en tres sitios distintos (citas entre sí, extraescolares entre sí y
citas contra extraescolares), así que vive aquí y no copiada tres veces.

Los tramos son enteros **minutos desde medianoche**, porque comparar `time` obliga a
convertir en cada comparación y a acordarse del mismo formato en cada módulo. Quien
venga de un `time` usa `_a_minutos` de `app.services.day`.
"""

from __future__ import annotations

from collections.abc import Iterable

# `inicio` y `fin` en minutos desde medianoche.
Tramo = tuple[int, int]


def une(tramos: Iterable[Tramo]) -> list[Tramo]:
    """Los tramos fundidos en unos pocos, ordenados y sin repetir lo solapado.

    Los tramos vacíos o invertidos (`fin <= inicio`) se descartan: son datos
    corruptos, y contarlos como bloqueo sería peor que ignorarlos.
    """
    utiles = sorted((a, z) for a, z in tramos if z > a)
    if not utiles:
        return []

    fundidos = [utiles[0]]
    for a, z in utiles[1:]:
        inicio, fin = fundidos[-1]
        if a <= fin:
            fundidos[-1] = (inicio, max(fin, z))
        else:
            fundidos.append((a, z))
    return fundidos


def minutos(tramos: Iterable[Tramo]) -> int:
    """Minutos que ocupa la unión de los tramos, contando cada solape una vez."""
    return sum(z - a for a, z in une(tramos))