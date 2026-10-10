"""
Chequeos de la revisión que no necesitan el LLM.

  CHEQUEOS          los criterios con `revisa: codigo` de las rúbricas, por id. Cada uno
                    devuelve (estado, evidencia) o None si no puede decidir; entonces el
                    criterio lo juzga el LLM.
  respaldada        si la evidencia que citó el LLM está de verdad en el documento. Es la
                    regla que impide marcar «cumple» sin evidencia: un modelo pequeño a
                    veces cita un texto que no existe.
  leer_veredicto    el JSON del LLM, tolerante a texto alrededor del objeto.

Prueba rápida, desde backend/ (sin modelos):
    python -m app.revision.chequeos tests/datos/adjuntos/perfil.docx
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

from app.adjuntos.tipos import ArchivoExtraido

# Fracción de la cita que tiene que aparecer seguida en el documento para darla por
# respaldada. Deja pasar un agregado corto en un extremo de la cita, pero no una paráfrasis.
MINIMO_RESPALDO = 0.85
# Una cita más corta que esto no respalda nada («sí», «rol»).
MINIMO_CARACTERES_CITA = 8

_TITULO_MD = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
# Títulos de un perfil: «Perfil: persona mayor…», «Perfil 2 - Rosa». No cuentan los títulos
# generales del documento («Perfil de persona usuaria», «Perfiles de personas usuarias»).
_PERFIL = re.compile(r"^perfil\b")
_GENERAL = re.compile(r"^perfil(es)? de (la |las )?personas? usuarias?$")


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes, sin marcas de markdown ni puntuación, con un espacio entre palabras."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^\w\[\]]+", " ", texto).strip()


def titulos(archivo: ArchivoExtraido) -> list[str]:
    """Títulos del documento, en orden y sin repetir: los de cada sección y los «#» dentro del texto."""
    vistos: list[str] = []
    for s in archivo.secciones:
        for t in ([s.titulo] if s.titulo else []) + _TITULO_MD.findall(s.texto):
            if t not in vistos:
                vistos.append(t)
    return vistos


def titulos_de_perfil(archivo: ArchivoExtraido) -> list[str]:
    """Títulos que abren un perfil («Perfil: …»), sin el título general del documento."""
    return [t for t in titulos(archivo) if _PERFIL.match(normalizar(t)) and not _GENERAL.match(normalizar(t))]


def cantidad_de_perfiles(archivo: ArchivoExtraido) -> tuple[str, str] | None:
    """
    Paso 2 de la guía: si el documento trae varios perfiles, entre tres y cinco.

    Cuenta los títulos que empiezan con «Perfil». Sin ninguno no puede saber
    cuántos hay (el perfil puede no tener título): devuelve None y decide el LLM.
    """
    perfiles = titulos_de_perfil(archivo)
    if not perfiles:
        return None
    lista = "; ".join(f"«{t}»" for t in perfiles)
    if len(perfiles) == 1:
        return "cumple", f"El documento describe un perfil: {lista}."
    estado = "cumple" if 3 <= len(perfiles) <= 5 else "no_cumple"
    return estado, f"El documento describe {len(perfiles)} perfiles: {lista}."


CHEQUEOS: dict[str, Callable[[ArchivoExtraido], tuple[str, str] | None]] = {
    "cantidad": cantidad_de_perfiles,
}


def respaldada(cita: str, documento: str) -> bool:
    """
    True si `cita` está en `documento`, sin mirar mayúsculas, tildes, puntuación ni markdown.

    Acepta que el LLM omita partes con «…» o «...» si cada trozo está en el documento,
    y diferencias menores: basta con que MINIMO_RESPALDO de la cita aparezca seguida.
    """
    trozos = [normalizar(t) for t in re.split(r"…|\.\.\.", cita)]
    trozos = [t for t in trozos if t]
    if sum(len(t) for t in trozos) < MINIMO_CARACTERES_CITA:
        return False
    doc = normalizar(documento)
    if all(t in doc for t in trozos):
        return True
    cita_n = " ".join(trozos)
    bloque = SequenceMatcher(None, cita_n, doc, autojunk=False).find_longest_match(0, len(cita_n), 0, len(doc))
    return bloque.size >= MINIMO_RESPALDO * len(cita_n)


def leer_veredicto(texto: str) -> dict | None:
    """El objeto JSON que devolvió el LLM, o None si no hay uno válido."""
    for candidato in (texto, texto[texto.find("{"):texto.rfind("}") + 1]):
        try:
            datos = json.loads(candidato)
        except ValueError:
            continue
        if isinstance(datos, dict):
            return datos
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", type=Path, help="documento (PDF, DOCX o MD); con PDF carga Docling")
    args = ap.parse_args()
    from app.adjuntos.extraer import extraer

    archivo = extraer(args.archivo.name, args.archivo.read_bytes())
    print("Títulos:", titulos(archivo))
    for criterio, chequeo in CHEQUEOS.items():
        print(f"{criterio}: {chequeo(archivo) or 'no decide: lo juzga el LLM'}")


if __name__ == "__main__":
    main()
