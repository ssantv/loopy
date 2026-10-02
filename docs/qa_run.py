"""Ejecuta un guion de QA sin dejar rastro en la base de datos de desarrollo.

Los guiones de `docs/` crean cuentas contra la API real, que trabaja sobre
`api/loopy_dev.db`. Como no se limpian solos, cada pasada dejaba cuentas `qa_*`
y la BD de demo se iba llenando de basura.

En vez de tocar los veinte y pico guiones uno a uno, esto envuelve la ejecucion:
apunta el id mas alto de `users` antes de empezar y, al terminar (pase o falle),
borra todo lo que se haya creado despues. Como todas las tablas cuelgan de
`users` con `ON DELETE CASCADE`, se lleva por delante cada tarea, sesion, receta
o plan que los guiones hubieran dejado.

Ojo: esto solo limpia si el guion se lanza a traves del envoltorio. Un
`node docs/qa-driver.mjs` a pelo deja las cuentas dentro, que es como se
acabo bloqueando la BD de desarrollo varias veces.

Uso (desde la raiz del repo):

    python docs/qa_run.py -- api\\.venv\\Scripts\\python.exe docs\\qa-adult.py
    python docs/qa_run.py -- node docs/qa-driver.mjs http://localhost:5173 --script docs/qa-home.mjs

Lo normal no es llamarlo a mano: `npm run qa` y `npm run qa:build` ya lo hacen
por cada guion. Ver docs/qa.md.

Todo lo que va despues del script es el comando a ejecutar, tal cual. El `--`
inicial es opcional.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "api" / "loopy_dev.db"

# La salida de los guiones de navegador trae flechas "→" y la consola de
# Windows va en cp1252: sin esto, el envoltorio revienta al copiarla.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def abrir() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA foreign_keys = ON")
    return con


# El runner del navegador no falla con código de salida cuando el guion revienta
# dentro de la página: lo deja escrito como texto y sale con 0. Sin esto, un QA
# roto se cuela como verde.
FALLOS = ("SCRIPT ERROR", "SNAPSHOT ERROR", "EVAL ERROR")


def run(argv: list[str]) -> int:
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    caido = False
    for linea in proc.stdout:
        if any(m in linea for m in FALLOS):
            caido = True
        print(linea, end="")
    codigo = proc.wait()
    if caido and codigo == 0:
        print("qa-run: el guion fallo dentro de la pagina (arriba).")
        return 1
    return codigo


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
        codigo = run(argv)
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
