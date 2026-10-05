"""
Credenciales del backend en el gestor de secretos del sistema operativo.

Las credenciales no quedan en texto plano en .env: se guardan con `keyring`, que
usa el Llavero de macOS, el Administrador de credenciales de Windows o el Secret
Service de Linux (GNOME Keyring, KWallet). Quedan cifradas en el equipo, fuera
del repositorio, y no aparecen en el historial de la terminal porque el valor se
pide sin mostrarlo.

config.py busca cada credencial en este orden:
  1. variable de entorno o .env (sirve para CI o servidores sin llavero);
  2. llavero del sistema, en el servicio SERVICIO y con el nombre de la variable.

Las credenciales son SUPABASE_DB_URL y LLM_API_KEY (solo si el LLM es un servicio
que pide clave). Las claves VITE_ quedan en .env:
Vite las incrusta en el navegador, así que no son secretas (la anon key es
pública y la protege RLS).

Uso, desde backend/:
    python -m app.rag.secretos guardar SUPABASE_DB_URL     # pide el valor sin mostrarlo
    python -m app.rag.secretos desde-env SUPABASE_DB_URL   # lo mueve de .env al llavero
    python -m app.rag.secretos ver SUPABASE_DB_URL         # dice si está guardada
    python -m app.rag.secretos borrar SUPABASE_DB_URL

Para pasarla a otro programa sin escribirla, por ejemplo a psql:
    psql "$(python -m app.rag.secretos exportar SUPABASE_DB_URL)"
"""
from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

# Nombre con el que se agrupan las credenciales del proyecto en el llavero.
SERVICIO = "guia-permitido-innovar"
# Credenciales que se pueden guardar. Una nueva se agrega aquí y en config.py.
SECRETOS = ("SUPABASE_DB_URL", "LLM_API_KEY")

RAIZ = Path(__file__).resolve().parents[3]  # raíz del repositorio


def leer(nombre: str) -> str | None:
    """Valor guardado en el llavero, o None si no está o no hay llavero disponible."""
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return None
    try:
        return keyring.get_password(SERVICIO, nombre)
    except KeyringError:
        return None


def guardar(nombre: str, valor: str) -> None:
    """Guarda el valor en el llavero, reemplazando el anterior, y comprueba que quedó."""
    import keyring

    keyring.set_password(SERVICIO, nombre, valor)
    if keyring.get_password(SERVICIO, nombre) != valor:
        raise RuntimeError(f"El llavero no devolvió el mismo valor de {nombre}; no se guardó.")


def borrar(nombre: str) -> bool:
    """Borra el valor del llavero. Devuelve False si no estaba."""
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(SERVICIO, nombre)
    except PasswordDeleteError:
        return False
    return True


def _pedir(nombre: str) -> str:
    """Pide el valor sin mostrarlo. Si la entrada no es una terminal, lo lee de ella (pbpaste | ...)."""
    if sys.stdin.isatty():
        valor = getpass.getpass(f"{nombre} (no se muestra al escribir): ")
    else:
        valor = sys.stdin.readline()
    return valor.strip()


def _linea_de(nombre: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*(export\s+)?{re.escape(nombre)}\s*=")


def desde_env(nombre: str, ruta: Path = RAIZ / ".env") -> None:
    """Mueve el valor de .env al llavero y deja la variable vacía en .env."""
    from dotenv import dotenv_values

    if not ruta.exists():
        sys.exit(f"No existe {ruta}.")
    valor = (dotenv_values(ruta).get(nombre) or "").strip()
    if not valor:
        sys.exit(f"{nombre} ya está vacía en {ruta.name}; usa «guardar» para escribirla en el llavero.")
    guardar(nombre, valor)
    patron = _linea_de(nombre)
    lineas = ruta.read_text(encoding="utf-8").splitlines(keepends=True)
    ruta.write_text("".join(f"{nombre}=\n" if patron.match(x) else x for x in lineas), encoding="utf-8")
    print(f"{nombre} quedó en el llavero (servicio «{SERVICIO}») y vacía en {ruta.name}.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=("guardar", "desde-env", "ver", "exportar", "borrar"))
    p.add_argument("nombre", choices=SECRETOS)
    a = p.parse_args()

    if a.accion == "guardar":
        valor = _pedir(a.nombre)
        if not valor:
            sys.exit("No se guardó nada: el valor está vacío.")
        guardar(a.nombre, valor)
        print(f"{a.nombre} quedó en el llavero (servicio «{SERVICIO}»).")
    elif a.accion == "desde-env":
        desde_env(a.nombre)
    elif a.accion == "ver":
        valor = leer(a.nombre)
        print(f"{a.nombre}: guardada en el llavero ({len(valor)} caracteres)." if valor
              else f"{a.nombre}: no está en el llavero.")
    elif a.accion == "exportar":
        valor = leer(a.nombre)
        if not valor:
            sys.exit(f"{a.nombre} no está en el llavero. Guárdala con: "
                     f"python -m app.rag.secretos guardar {a.nombre}")
        print(valor)
    elif a.accion == "borrar":
        print(f"{a.nombre} se borró del llavero." if borrar(a.nombre)
              else f"{a.nombre} no estaba en el llavero.")


if __name__ == "__main__":
    main()
