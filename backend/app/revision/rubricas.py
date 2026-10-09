"""
Rúbricas de revisión: lo que pide la guía para cada herramienta, punto por punto.

Cada herramienta tiene un archivo en data/rubricas/<id>.yaml, versionado en el
repositorio (el formato está comentado en cada archivo). Van en YAML y no en el
código para que se puedan revisar contra la guía sin leer Python.

cargar() valida la rúbrica al leerla: un tipo, un `revisa` o una página que no
existen fallan con ValueError, en vez de dar una revisión a medias. No importa
LlamaIndex ni modelos: la usa también el simulador.

Para ver una rúbrica, desde backend/:
    python -m app.revision.rubricas perfil_persona_usuaria
    python -m app.revision.rubricas            # lista las disponibles
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from functools import cache

import yaml

from app.rag import config

RUTA_RUBRICAS = config.RAIZ / "data" / "rubricas"
TIPOS = ("obligatorio", "recomendado")
REVISA = ("llm", "codigo")
# Páginas de la guía (la última es la contratapa).
PAGINAS_GUIA = range(1, 171)


@dataclass(frozen=True)
class Criterio:
    """Un punto de lo que pide la guía para la herramienta."""

    id: str
    nombre: str
    tipo: str                  # uno de TIPOS
    revisa: str                # uno de REVISA
    pagina: int
    pide: str
    sugerencia: str
    paso: int | None = None
    parcial: str | None = None  # cuándo está incompleto; None: está o falta

    def cita(self) -> str:
        """«p. 148, paso 3»: dónde lo pide la guía."""
        return f"p. {self.pagina}, paso {self.paso}" if self.paso else f"p. {self.pagina}"


@dataclass(frozen=True)
class Rubrica:
    """Lo que pide la guía para una herramienta."""

    id: str
    nombre: str
    version: str
    validada: bool            # true cuando UXLab la aprueba
    fuente: str               # cita de la herramienta, como la línea «fuente:» del corpus
    pagina: int
    descripcion: str          # para qué sirve la herramienta, en una frase
    resumen: str              # qué debe decir el resumen breve de lo cargado
    criterios: tuple[Criterio, ...]

    def obligatorios(self) -> list[Criterio]:
        return [c for c in self.criterios if c.tipo == "obligatorio"]


def _texto(valor: object) -> str:
    """Texto de YAML en una línea: los «>-» ya juntan líneas, pero quedan espacios dobles."""
    return re.sub(r"\s+", " ", str(valor)).strip()


def _criterio(datos: dict, archivo: str) -> Criterio:
    falta = {"id", "nombre", "tipo", "revisa", "pagina", "pide", "sugerencia"} - set(datos)
    if falta:
        raise ValueError(f"{archivo}: al criterio {datos.get('id', '?')} le falta {', '.join(sorted(falta))}.")
    c = Criterio(id=str(datos["id"]), nombre=_texto(datos["nombre"]), tipo=datos["tipo"], revisa=datos["revisa"],
                 pagina=int(datos["pagina"]), pide=_texto(datos["pide"]), sugerencia=_texto(datos["sugerencia"]),
                 paso=int(datos["paso"]) if datos.get("paso") is not None else None,
                 parcial=_texto(datos["parcial"]) if datos.get("parcial") else None)
    if c.tipo not in TIPOS:
        raise ValueError(f"{archivo}: el criterio {c.id} tiene tipo {c.tipo!r}; usa {' o '.join(TIPOS)}.")
    if c.revisa not in REVISA:
        raise ValueError(f"{archivo}: el criterio {c.id} tiene revisa {c.revisa!r}; usa {' o '.join(REVISA)}.")
    if c.pagina not in PAGINAS_GUIA:
        raise ValueError(f"{archivo}: el criterio {c.id} cita la p. {c.pagina}, que la guía no tiene.")
    return c


def disponibles() -> list[str]:
    """Ids de las rúbricas que hay en data/rubricas/."""
    return sorted(p.stem for p in RUTA_RUBRICAS.glob("*.yaml"))


@cache
def cargar(herramienta: str) -> Rubrica:
    """
    La rúbrica de `herramienta` (su id, p. ej. «perfil_persona_usuaria»).

    KeyError si no existe; ValueError si el archivo tiene un error.
    """
    if herramienta not in disponibles():
        raise KeyError(f"No hay rúbrica para «{herramienta}». Disponibles: {', '.join(disponibles())}.")
    archivo = f"{herramienta}.yaml"
    datos = yaml.safe_load((RUTA_RUBRICAS / archivo).read_text(encoding="utf-8"))
    if datos.get("id") != herramienta:
        raise ValueError(f"{archivo}: el id ({datos.get('id')!r}) tiene que ser el nombre del archivo.")
    criterios = tuple(_criterio(c, archivo) for c in datos.get("criterios") or [])
    if not criterios:
        raise ValueError(f"{archivo}: no tiene criterios.")
    ids = [c.id for c in criterios]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{archivo}: hay ids de criterio repetidos.")
    return Rubrica(id=herramienta, nombre=_texto(datos["nombre"]), version=str(datos["version"]),
                   validada=bool(datos.get("validada", False)), fuente=_texto(datos["fuente"]),
                   pagina=int(datos["pagina"]), descripcion=_texto(datos["descripcion"]),
                   resumen=_texto(datos["resumen"]), criterios=criterios)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("herramienta", nargs="?", help="id de la rúbrica; sin él, lista las disponibles")
    args = ap.parse_args()
    if not args.herramienta:
        print("\n".join(disponibles()))
        return
    r = cargar(args.herramienta)
    estado = "validada por UXLab" if r.validada else "sin validar"
    print(f"{r.nombre} · versión {r.version} · {estado} · {r.fuente}\n")
    for c in r.criterios:
        print(f"[{c.tipo} · {c.revisa} · {c.cita()}] {c.nombre}\n   {c.pide}")
        if c.parcial:
            print(f"   incompleto si: {c.parcial}")


if __name__ == "__main__":
    main()
