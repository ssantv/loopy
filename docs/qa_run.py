"""Ejecuta un guion de QA sin dejar rastro en la base de datos de desarrollo.

Los guiones de `docs/` crean cuentas contra la API real, que trabaja sobre
`api/loopy_dev.db`. Como no se limpian solos, cada pasada dejaba cuentas `qa_*`
y la BD de demo se iba llenando de basura.

En vez de tocar los veinte y pico guiones uno a uno, esto envuelve la ejecucion:
apunta el id mas alto de `users` antes de empezar y, al terminar (pase o falle),
borra todo lo que se haya creado despues. Como todas las tablas cuelgan de
`users` con `ON DELETE CASCADE`, se lleva por delante cada tarea, sesion, receta
o plan que los guiones hubieran dejado.

Uso (desde la raiz del repo):

    python docs/qa_run.py -- api\\.venv\\Scripts\\python.exe docs\\qa-adult.py
    python docs/qa_run.py -- node <ruta-a-browser.mjs> http://localhost:5173 --script docs\\qa-home.mjs

Todo lo que va despues del script es el comando a ejecutar, tal cual. El `--`
inicial es opcional.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "api" / "loopy_dev.db"


def abrir() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(__doc__)
        return 2
    if not DB.exists():
        print(f"qa-run: no encuentro la BD en {DB}", file=sys.stderr)
        return 2

    con = abrir()
    marca = con.execute("SELECT COALESCE(MAX(id), 0) FROM users").fetchone()[0]
    con.close()

    print(f"qa-run: marca users.id = {marca}")
    print(f"qa-run: ejecutando -> {' '.join(argv)}")

    codigo = 1
    try:
        codigo = subprocess.call(argv)
    finally:
        con = abrir()
        creadas = con.execute(
            "SELECT COUNT(*) FROM users WHERE id > ?", (marca,)
        ).fetchone()[0]
        if creadas:
            con.execute("DELETE FROM users WHERE id > ?", (marca,))
            con.commit()
        quedan = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        con.close()
        print(f"qa-run: {creadas} cuentas de prueba borradas en cascada; quedan {quedan}")
        print(f"qa-run: el guion salio con codigo {codigo}")

    return codigo


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
