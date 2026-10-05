"""
Credenciales del backend: en el llavero del sistema si hay uno, si no en .env.

Donde se puede, las credenciales no quedan en texto plano: se guardan con
`keyring`, que usa el Llavero de macOS, el Administrador de credenciales de
Windows o el Secret Service de Linux (GNOME Keyring, KWallet). Quedan cifradas en
el equipo, fuera del repositorio.

No todos los equipos tienen llavero: WSL, un Linux sin escritorio o un
contenedor no traen Secret Service. Ahí el mismo comando «guardar» escribe la
credencial en el .env de la raíz (que git ignora) y deja el archivo legible solo
para tu usuario. También se puede elegir .env a propósito con --en-env, por
ejemplo si el llavero de Linux pide la contraseña en cada consulta. En los dos
casos el valor se pide sin mostrarlo, así que no queda en el historial de la
terminal.

config.py busca cada credencial en este orden:
  1. variable de entorno o .env (equipos sin llavero, CI, servidores);
  2. llavero del sistema, en el servicio SERVICIO y con el nombre de la variable.

Las credenciales son SUPABASE_DB_URL, LLM_API_KEY (solo si el LLM es un servicio
que pide clave) y CLAVE_SERVICIO (la que la API le exige a la plataforma).

Uso, desde backend/:
    python -m app.rag.secretos donde                       # dice si este equipo tiene llavero
    python -m app.rag.secretos guardar SUPABASE_DB_URL     # pide el valor sin mostrarlo
    python -m app.rag.secretos guardar SUPABASE_DB_URL --en-env   # en .env aunque haya llavero
    python -m app.rag.secretos desde-env SUPABASE_DB_URL   # la mueve de .env al llavero
    python -m app.rag.secretos ver SUPABASE_DB_URL         # dice dónde está guardada
    python -m app.rag.secretos borrar SUPABASE_DB_URL

Para pasarla a otro programa sin escribirla, por ejemplo a psql:
    psql "$(python -m app.rag.secretos exportar SUPABASE_DB_URL)"
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

# Nombre con el que se agrupan las credenciales del proyecto en el llavero.
SERVICIO = "guia-permitido-innovar"
# Credenciales que se pueden guardar. Una nueva se agrega aquí y en config.py.
SECRETOS = ("SUPABASE_DB_URL", "LLM_API_KEY", "CLAVE_SERVICIO")

RAIZ = Path(__file__).resolve().parents[3]  # raíz del repositorio
ENV = RAIZ / ".env"


def hay_llavero() -> bool:
    """
    True si keyring tiene un llavero real en este equipo.

    Sin llavero, keyring elige el backend «fail» (prioridad 0, falla en cada
    operación) o «null» (prioridad -1, no guarda nada); los reales tienen
    prioridad positiva.
    """
    try:
        import keyring
    except ImportError:  # requirements-simulador.txt no instala keyring
        return False
    try:
        return keyring.get_keyring().priority > 0
    except Exception:  # un backend que no puede decir su prioridad tampoco sirve
        return False


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


def leer_archivo(nombre: str, ruta: Path = ENV) -> str | None:
    """Valor escrito en el archivo .env, o None si no existe o la variable está vacía."""
    if not ruta.exists():
        return None
    from dotenv import dotenv_values

    return (dotenv_values(ruta).get(nombre) or "").strip() or None


def leer_env(nombre: str, ruta: Path = ENV) -> str | None:
    """Valor de la variable de entorno o, si no está, del archivo .env. None si no está en ninguno."""
    return (os.environ.get(nombre) or "").strip() or leer_archivo(nombre, ruta)


def guardar(nombre: str, valor: str) -> None:
    """Guarda el valor en el llavero, reemplazando el anterior, y comprueba que quedó."""
    import keyring

    keyring.set_password(SERVICIO, nombre, valor)
    if keyring.get_password(SERVICIO, nombre) != valor:
        raise RuntimeError(f"El llavero no devolvió el mismo valor de {nombre}; no se guardó.")


def _comillas(valor: str) -> str:
    """
    Valor entre comillas simples, para que dotenv no corte en # ni en espacios.

    dotenv expande ${...} incluso entre comillas y no tiene cómo escaparlo: un
    valor así cambiaría al leerlo, así que no se escribe.
    """
    if "${" in valor:
        raise ValueError("El valor contiene «${», que .env reemplazaría al leerlo. "
                         "Cambia esa contraseña o define la variable en el entorno.")
    return "'" + valor.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _linea_de(nombre: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*(export\s+)?{re.escape(nombre)}\s*=")


def escribir_env(nombre: str, valor: str, ruta: Path = ENV) -> None:
    """
    Escribe NOMBRE=valor en .env: reemplaza la línea si ya estaba y si no la agrega al final.

    Con valor vacío la deja como «NOMBRE=». El archivo queda legible solo para tu
    usuario (en Windows chmod no cambia los permisos de lectura, pero .env está en
    tu carpeta de usuario y fuera de git).
    """
    linea = f"{nombre}={_comillas(valor) if valor else ''}\n"
    patron = _linea_de(nombre)
    lineas = ruta.read_text(encoding="utf-8").splitlines(keepends=True) if ruta.exists() else []
    if any(patron.match(x) for x in lineas):
        lineas = [linea if patron.match(x) else x for x in lineas]
    else:
        if lineas and not lineas[-1].endswith("\n"):
            lineas[-1] += "\n"
        lineas.append(linea)
    ruta.write_text("".join(lineas), encoding="utf-8")
    os.chmod(ruta, 0o600)


def guardar_donde_se_pueda(nombre: str, valor: str, en_env: bool = False, ruta: Path = ENV) -> str:
    """Guarda en el llavero si hay uno (y no se pidió .env); si no, en .env. Devuelve dónde quedó."""
    if not en_env and hay_llavero():
        guardar(nombre, valor)
        if leer_archivo(nombre, ruta):
            # .env manda sobre el llavero: un valor viejo ahí taparía el nuevo.
            escribir_env(nombre, "", ruta)
        return f"el llavero (servicio «{SERVICIO}»)"
    escribir_env(nombre, valor, ruta)
    return ruta.name


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


def desde_env(nombre: str, ruta: Path = ENV) -> None:
    """Mueve el valor de .env al llavero y deja la variable vacía en .env."""
    if not hay_llavero():
        sys.exit(f"Este equipo no tiene llavero: {nombre} se queda en {ruta.name}, que es donde se lee.")
    if not ruta.exists():
        sys.exit(f"No existe {ruta}.")
    valor = leer_archivo(nombre, ruta)
    if not valor:
        sys.exit(f"{nombre} ya está vacía en {ruta.name}; usa «guardar» para escribirla en el llavero.")
    guardar(nombre, valor)
    escribir_env(nombre, "", ruta)
    print(f"{nombre} quedó en el llavero (servicio «{SERVICIO}») y vacía en {ruta.name}.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=("donde", "guardar", "desde-env", "ver", "exportar", "borrar"))
    p.add_argument("nombre", nargs="?", choices=SECRETOS)
    p.add_argument("--en-env", action="store_true", help="con «guardar»: usa .env aunque haya llavero")
    a = p.parse_args()

    if a.accion == "donde":
        print(f"Este equipo tiene llavero: las credenciales van ahí (servicio «{SERVICIO}»)." if hay_llavero()
              else f"Este equipo no tiene llavero: las credenciales van en {ENV.name}, legible solo para tu usuario.")
        return
    if not a.nombre:
        p.error(f"«{a.accion}» necesita el nombre de la credencial: {', '.join(SECRETOS)}.")

    if a.accion == "guardar":
        valor = _pedir(a.nombre)
        if not valor:
            sys.exit("No se guardó nada: el valor está vacío.")
        try:
            donde = guardar_donde_se_pueda(a.nombre, valor, en_env=a.en_env)
        except ValueError as e:
            sys.exit(str(e))
        aviso = "" if a.en_env or donde != ENV.name else " Este equipo no tiene llavero; .env no se versiona."
        print(f"{a.nombre} quedó en {donde}.{aviso}")
    elif a.accion == "desde-env":
        desde_env(a.nombre)
    elif a.accion == "ver":
        if valor := leer_env(a.nombre):
            print(f"{a.nombre}: definida en el entorno o en {ENV.name} ({len(valor)} caracteres).")
        elif valor := leer(a.nombre):
            print(f"{a.nombre}: guardada en el llavero ({len(valor)} caracteres).")
        else:
            print(f"{a.nombre}: no está ni en {ENV.name} ni en el llavero.")
    elif a.accion == "exportar":
        # Mismo orden que config.py: entorno o .env, después llavero.
        valor = leer_env(a.nombre) or leer(a.nombre)
        if not valor:
            sys.exit(f"{a.nombre} no está guardada. Guárdala con: python -m app.rag.secretos guardar {a.nombre}")
        print(valor)
    elif a.accion == "borrar":
        borrada = False
        if hay_llavero() and borrar(a.nombre):
            borrada = True
        if leer_archivo(a.nombre):
            escribir_env(a.nombre, "", ENV)
            borrada = True
        print(f"{a.nombre} se borró." if borrada else f"{a.nombre} no estaba guardada.")


if __name__ == "__main__":
    main()
