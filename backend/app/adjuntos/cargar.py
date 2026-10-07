"""
Carga un adjunto: lo lee, lo seudonimiza y lo indexa en memoria (lo que hace POST /ia/adjuntos).

    extraer.extraer → seudonimizar (cada sección y su título) → indice.indexar

Las secciones se seudonimizan en orden pasando las correspondencias de una a la
siguiente, para que el mismo RUT o correo tenga el mismo marcador en todo el
documento. Los títulos también se seudonimizan: van en la cita («Adjunto ›
<título>») que ve el LLM.

Prueba rápida, desde backend/ (con un PDF carga los modelos de layout; siempre bge-m3):
    python -m app.adjuntos.cargar tests/datos/adjuntos/perfil.docx --json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app.adjuntos.extraer import extraer
from app.adjuntos.indice import indexar
from app.adjuntos.seudonimizar import seudonimizar
from app.adjuntos.tipos import AdjuntoCargado, ArchivoExtraido, ErrorAdjunto, Seccion


def seudonimizar_archivo(archivo: ArchivoExtraido) -> tuple[ArchivoExtraido, dict[str, str], dict[str, int]]:
    """El archivo con cada sección y título seudonimizados, la tabla de correspondencias y los reemplazos."""
    tabla: dict[str, str] = {}
    reemplazos: Counter[str] = Counter()
    secciones = []
    for s in archivo.secciones:
        titulo = None
        if s.titulo:
            t = seudonimizar(s.titulo, tabla)
            titulo, tabla = t.texto, t.correspondencias
            reemplazos.update(t.reemplazos)
        texto = seudonimizar(s.texto, tabla)
        tabla = texto.correspondencias
        reemplazos.update(texto.reemplazos)
        secciones.append(Seccion(texto=texto.texto, pagina=s.pagina, titulo=titulo))
    limpio = ArchivoExtraido(nombre=archivo.nombre, formato=archivo.formato, secciones=secciones,
                             paginas=archivo.paginas)
    return limpio, tabla, dict(reemplazos)


def cargar_adjunto(nombre: str, datos: bytes) -> AdjuntoCargado:
    """
    Lee, seudonimiza e indexa un adjunto. ErrorAdjunto si el archivo no sirve
    (formato, tamaño, páginas, sin texto); RuntimeError si fallan los modelos.
    """
    t0 = time.time()
    limpio, tabla, reemplazos = seudonimizar_archivo(extraer(nombre, datos))
    adjunto = indexar(limpio, tabla, reemplazos)
    adjunto.latencia_s = round(time.time() - t0, 1)
    return adjunto


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", type=Path)
    ap.add_argument("--json", action="store_true", help="salida con la forma de la respuesta de la API")
    args = ap.parse_args()
    try:
        adjunto = cargar_adjunto(args.archivo.name, args.archivo.read_bytes())
    except ErrorAdjunto as e:
        sys.exit(f"[{e.estado}] {e.mensaje}")
    if args.json:
        print(json.dumps(adjunto.a_dict(), ensure_ascii=False, indent=2))
        return
    print(f"{adjunto.formato} · {adjunto.paginas or '—'} páginas · {adjunto.fragmentos} fragmentos · "
          f"{adjunto.caracteres} caracteres · reemplazos {adjunto.reemplazos or 'ninguno'} · "
          f"{adjunto.latencia_s} s")


if __name__ == "__main__":
    main()
