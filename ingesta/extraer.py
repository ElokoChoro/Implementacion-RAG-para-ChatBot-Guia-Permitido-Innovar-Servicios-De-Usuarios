"""
Paso 1: extrae la guía desde el PDF con Docling, pipeline `standard` sin OCR
(ADR-06). Guarda el DoclingDocument en JSON, que trae la página de cada bloque.

La salida cruda (~3 MB) no se versiona (ADR-11): queda en data/docling/, que
está en .gitignore. Lo que se versiona es el corpus que genera `ingesta.corpus`.

    python -m ingesta.extraer /ruta/a/Guia_ComoInnovar.pdf

Tarda ~2 min en un Mac M2 de 8 GB. La primera vez descarga los modelos de layout.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import time
from pathlib import Path

import yaml
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import settings
from docling.document_converter import DocumentConverter, PdfFormatOption

RAIZ = Path(__file__).resolve().parent.parent
MANIFIESTO = RAIZ / "data" / "fuentes" / "guia.yaml"
SALIDA = RAIZ / "data" / "docling" / "Guia_ComoInnovar.json"


def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def convertidor() -> DocumentConverter:
    opciones = PdfPipelineOptions()
    opciones.do_ocr = False              # se usa la capa de texto del PDF
    opciones.do_table_structure = True
    opciones.generate_picture_images = False  # basta con el texto dentro de las figuras
    settings.perf.page_batch_size = 2    # menos memoria en equipos de 8 GB
    return DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=opciones)})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    args = ap.parse_args()

    esperado = yaml.safe_load(MANIFIESTO.read_text(encoding="utf-8"))["pdf"]["sha256"]
    obtenido = sha256(args.pdf)
    if obtenido != esperado:
        print(f"¡Ojo! El PDF no coincide con {MANIFIESTO.relative_to(RAIZ)}:\n"
              f"  esperado {esperado}\n  obtenido {obtenido}\n"
              "Si la guía cambió, actualiza el manifiesto y la versión del corpus.")

    t0 = time.time()
    doc = convertidor().convert(args.pdf).document
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    doc.save_as_json(SALIDA)
    print(f"{len(doc.pages)} páginas en {time.time() - t0:.0f} s "
          f"(docling {importlib.metadata.version('docling')}) -> {SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
