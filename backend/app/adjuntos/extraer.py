"""
Lee un adjunto (PDF, DOCX o MD) y lo divide en secciones con su página o su título.

validar() revisa, sin Docling, que el formato esté en FORMATOS_ADJUNTO, que el
contenido corresponda a la extensión (un .pdf que no empieza con «%PDF-» no
es un PDF) y que no pase de MAX_MB_ADJUNTO. La usa también el simulador.

extraer() convierte desde memoria, sin escribir a disco:

  PDF    Primero pypdfium2 (viene con Docling) cuenta las páginas y saca el texto
         crudo de cada una, sin modelos: así se rechazan antes de cargar el
         layout los PDF con contraseña, los de más de MAX_PAGINAS_ADJUNTO páginas
         y los escaneados (menos de MIN_CARACTERES_PAGINA por página, porque no
         hay OCR). Después Docling, con las mismas opciones que la ingesta de la
         guía (pipeline standard, sin OCR), ordena columnas y arma las tablas. Una
         sección por página.
  DOCX   Docling, con su backend de Word: no carga modelos (SimplePipeline).
  MD     Igual que DOCX. Una sección por cada título.

Docling se salta a veces bloques de texto: con el PDF de ejemplo
(tests/datos/adjuntos/perfil.pdf) dejó vacía la página 3, que solo tiene un
párrafo corto. Por eso cada página se compara con el texto crudo de pypdfium2
y, si Docling devuelve menos de la mitad de los caracteres, se usa el crudo.

Las tablas quedan en markdown («| col | col |»), que es como mejor las lee el LLM.

Prueba rápida, desde backend/ (con un PDF carga los modelos de layout, ~0,9 GB):
    python -m app.adjuntos.extraer tests/datos/adjuntos/perfil.docx
    python -m app.adjuntos.extraer tests/datos/adjuntos/perfil.pdf --json
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
import time
import zipfile
from dataclasses import asdict
from functools import cache
from pathlib import Path

from app.adjuntos.tipos import FORMATOS, ArchivoExtraido, ErrorAdjunto, Seccion
from app.rag import config

log = logging.getLogger("app.adjuntos")

NOMBRES = {"pdf": "PDF", "docx": "DOCX", "md": "Markdown (.md)"}
# Si Docling deja menos de esta fracción del texto crudo de una página, se usa el crudo.
MINIMO_DOCLING = 0.5
_TITULO = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _aceptados() -> str:
    """«PDF o DOCX», «PDF, DOCX o Markdown (.md)»."""
    nombres = [NOMBRES[f] for f in config.FORMATOS_ADJUNTO]
    return nombres[0] if len(nombres) == 1 else f"{', '.join(nombres[:-1])} o {nombres[-1]}"


def validar(nombre: str, datos: bytes) -> str:
    """
    El formato del adjunto («pdf», «docx» o «md») si se puede leer; si no, ErrorAdjunto.

    No importa Docling ni abre el documento: solo mira la extensión, el tamaño y
    los primeros bytes.
    """
    formato = Path(nombre).suffix.lower().lstrip(".")
    if formato not in config.FORMATOS_ADJUNTO:
        raise ErrorAdjunto(f"Solo puedo leer archivos {_aceptados()}. Guarda tu documento en uno de esos "
                           "formatos y vuelve a subirlo.", 415)
    if not datos:
        raise ErrorAdjunto("El archivo está vacío. Revisa que sea el documento correcto y vuelve a subirlo.")
    maximo = config.MAX_MB_ADJUNTO * 1024 * 1024
    if len(datos) > maximo:
        raise ErrorAdjunto(f"El archivo pesa {len(datos) / 1024 / 1024:.1f} MB y el máximo es "
                           f"{config.MAX_MB_ADJUNTO:g} MB. Quítale imágenes o divídelo y vuelve a subirlo.", 413)
    if not _contenido_valido(formato, datos):
        raise ErrorAdjunto(f"El archivo dice ser {NOMBRES[formato]}, pero su contenido no lo es. Ábrelo en "
                           f"su programa, guárdalo como {NOMBRES[formato]} y vuelve a subirlo.", 415)
    return formato


def _contenido_valido(formato: str, datos: bytes) -> bool:
    if formato == "pdf":
        return b"%PDF-" in datos[:1024]  # la cabecera puede venir después de algunos bytes
    if formato == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                return "word/document.xml" in z.namelist()
        except zipfile.BadZipFile:
            return False
    try:  # md
        return "\x00" not in datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False


def es_escaneado(caracteres_por_pagina: list[int]) -> bool:
    """True si el PDF no tiene texto que leer: menos de MIN_CARACTERES_PAGINA por página en promedio."""
    if not caracteres_por_pagina:
        return True
    return sum(caracteres_por_pagina) / len(caracteres_por_pagina) < config.MIN_CARACTERES_PAGINA


def _texto_crudo_pdf(datos: bytes) -> list[str]:
    """Texto de cada página según pypdfium2, sin modelos. ErrorAdjunto si no se puede abrir."""
    import pypdfium2

    try:
        pdf = pypdfium2.PdfDocument(datos)
    except pypdfium2.PdfiumError as e:
        if "password" in str(e).lower():
            raise ErrorAdjunto("El PDF tiene contraseña. Quítasela (o expórtalo de nuevo sin protección) "
                               "y vuelve a subirlo.") from e
        raise ErrorAdjunto("No pude abrir el PDF: parece dañado. Expórtalo de nuevo desde su programa y "
                           "vuelve a subirlo.") from e
    try:
        if len(pdf) > config.MAX_PAGINAS_ADJUNTO:
            raise ErrorAdjunto(f"El PDF tiene {len(pdf)} páginas y el máximo es {config.MAX_PAGINAS_ADJUNTO}. "
                               "Sube solo la parte que quieres revisar.", 413)
        return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()


@cache
def _convertidor():
    """
    Conversor de Docling para los formatos que sabe leer. Qué se acepta lo decide validar(),
    con FORMATOS_ADJUNTO. Se crea una vez por proceso: con PDF carga los modelos de layout la
    primera vez que convierte.
    """
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.settings import settings
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # Mismas opciones que ingesta/extraer.py, con que se extrajo la guía (allí está el porqué).
    opciones = PdfPipelineOptions()
    opciones.do_ocr = False
    opciones.do_table_structure = True
    opciones.generate_picture_images = False
    settings.perf.page_batch_size = 2  # menos memoria en equipos de 8 GB
    formatos = {"pdf": InputFormat.PDF, "docx": InputFormat.DOCX, "md": InputFormat.MD}
    return DocumentConverter(allowed_formats=[formatos[f] for f in FORMATOS],
                             format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opciones)})


def _convertir(nombre: str, formato: str, datos: bytes):
    """DoclingDocument del adjunto. ErrorAdjunto si Docling no lo puede leer."""
    from docling.datamodel.base_models import DocumentStream

    try:
        # El nombre solo le indica el formato a Docling: no se usa el original, que puede traer nombres.
        return _convertidor().convert(DocumentStream(name=f"adjunto.{formato}", stream=io.BytesIO(datos))).document
    except Exception as e:  # cualquier falla al interpretar el archivo es un problema del archivo
        log.warning("Docling no pudo convertir un %s (%s).", formato, type(e).__name__)
        raise ErrorAdjunto(f"No pude leer el {NOMBRES[formato]}: puede estar dañado. Ábrelo en su programa, "
                           "guárdalo de nuevo y vuelve a subirlo.") from e


def _limpio(texto: str) -> str:
    """Sin espacios al final de cada línea ni más de una línea en blanco seguida."""
    lineas = [linea.rstrip() for linea in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def _sin_espacios(texto: str) -> int:
    return len(re.sub(r"\s", "", texto))


def secciones_por_titulo(markdown: str) -> list[Seccion]:
    """
    Divide un markdown en una sección por título («#» a «######»). El título queda
    también al inicio del texto, para que se vectorice con su contenido. Un título sin
    texto debajo (otro título justo después) no genera sección.
    """
    secciones: list[Seccion] = []
    titulo: str | None = None
    lineas: list[str] = []

    def cerrar() -> None:
        cuerpo = _limpio("\n".join(lineas))
        if cuerpo and cuerpo != (f"{titulo}" if titulo else ""):
            secciones.append(Seccion(texto=cuerpo, titulo=titulo))

    for linea in markdown.splitlines():
        m = _TITULO.match(linea)
        if m:
            cerrar()
            titulo, lineas = m.group(2).strip(), [m.group(2).strip()]
        else:
            lineas.append(linea)
    cerrar()
    return secciones


def _ultimo_titulo(markdown: str, anterior: str | None) -> str | None:
    titulos = [m.group(2).strip() for linea in markdown.splitlines() if (m := _TITULO.match(linea))]
    return titulos[-1] if titulos else anterior


def _extraer_pdf(nombre: str, datos: bytes) -> ArchivoExtraido:
    crudo = _texto_crudo_pdf(datos)
    if es_escaneado([_sin_espacios(t) for t in crudo]):
        raise ErrorAdjunto("El PDF parece escaneado: no tiene texto que pueda leer. Súbelo como DOCX o como PDF "
                           "exportado desde el editor de texto.")
    doc = _convertir(nombre, "pdf", datos)
    secciones: list[Seccion] = []
    titulo: str | None = None
    for n, texto_crudo in enumerate(crudo, start=1):
        texto = _limpio(doc.export_to_markdown(page_no=n, escape_html=False, image_placeholder=""))
        if _sin_espacios(texto) < MINIMO_DOCLING * _sin_espacios(texto_crudo):
            texto = _limpio(texto_crudo)  # Docling se saltó texto de esta página
        titulo_pagina = titulo  # el último título visto antes de la página
        titulo = _ultimo_titulo(texto, titulo)
        if texto:
            primero = _ultimo_titulo(texto.split("\n", 1)[0], None)
            secciones.append(Seccion(texto=texto, pagina=n, titulo=primero or titulo_pagina))
    return ArchivoExtraido(nombre=nombre, formato="pdf", secciones=secciones, paginas=len(crudo))


def extraer(nombre: str, datos: bytes) -> ArchivoExtraido:
    """
    Texto del adjunto en secciones: una por página (PDF) o por título (DOCX y MD).

    Lanza ErrorAdjunto si el archivo no es válido (ver validar), pasa de
    MAX_PAGINAS_ADJUNTO páginas, tiene contraseña, está dañado o no tiene texto.
    """
    formato = validar(nombre, datos)
    if formato == "pdf":
        archivo = _extraer_pdf(nombre, datos)
    else:
        doc = _convertir(nombre, formato, datos)
        archivo = ArchivoExtraido(nombre=nombre, formato=formato,
                                  secciones=secciones_por_titulo(doc.export_to_markdown(escape_html=False)))
    if not archivo.secciones:
        raise ErrorAdjunto(f"El {NOMBRES[formato]} no tiene texto que pueda leer. Revisa que sea el documento "
                           "correcto y vuelve a subirlo.")
    return archivo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", type=Path)
    ap.add_argument("--json", action="store_true", help="muestra las secciones completas en JSON")
    args = ap.parse_args()

    t0 = time.time()
    try:
        archivo = extraer(args.archivo.name, args.archivo.read_bytes())
    except ErrorAdjunto as e:
        sys.exit(f"[{e.estado}] {e.mensaje}")
    if args.json:
        print(json.dumps(asdict(archivo), ensure_ascii=False, indent=2))
        return
    print(f"{archivo.formato} · {archivo.paginas or '—'} páginas · {len(archivo.secciones)} secciones · "
          f"{archivo.caracteres()} caracteres · {time.time() - t0:.1f} s\n")
    for s in archivo.secciones:
        donde = f"p. {s.pagina}" if s.pagina else "—"
        print(f"[{donde} · {s.titulo or 'sin título'}] {s.texto[:160].replace(chr(10), ' ')}…")


if __name__ == "__main__":
    main()
