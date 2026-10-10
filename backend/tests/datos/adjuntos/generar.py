"""
Genera los adjuntos de ejemplo para los tests y las pruebas manuales.

Todos tienen el mismo «Perfil de persona usuaria», con datos ficticios: un
nombre, un RUT válido (dos veces, en dos formatos, para probar que recibe un
solo marcador), un correo y un teléfono.

    perfil.md       Markdown con dos títulos y una tabla
    perfil.docx     el mismo contenido, con python-docx (viene con Docling)
    perfil.pdf      el mismo contenido en 3 páginas, desde texto plano con cupsfilter (macOS)
    escaneado.pdf   una imagen sin capa de texto, como un documento escaneado (sips, macOS)
    no-es-pdf.pdf   texto plano con extensión .pdf

Desde la raíz del repositorio:
    .venv/bin/python backend/tests/datos/adjuntos/generar.py
"""
from __future__ import annotations

import argparse
import subprocess
import tempfile
import textwrap
from pathlib import Path

CARPETA = Path(__file__).resolve().parent

NOMBRE = "Paula Andrea Rojas Díaz"
RUT = "12.345.678-5"
RUT_SIN_PUNTOS = "12345678-5"
CORREO = "paula.rojas@ejemplo.cl"
TELEFONO = "+56 9 1234 5678"

AVISO = "Datos ficticios para probar el chatbot: no corresponden a personas reales."

# (título, párrafos); la tabla va en la segunda sección
SECCIONES: list[tuple[str, list[str]]] = [
    ("Proyecto", [
        "Servicio: renovación de la licencia de conducir en la Municipalidad de Villa Ejemplo.",
        f"Encargada del proyecto: {NOMBRE}, RUT {RUT}, correo {CORREO}, teléfono {TELEFONO}.",
        "Etapa: 2 Personas usuarias. Se entrevistó a 12 personas entre agosto y septiembre de 2026.",
    ]),
    ("Perfil: persona mayor que renueva su licencia", [
        "Rol: conductora de 68 años que renueva su licencia cada tres años y vive en un sector rural.",
        "Necesidades: saber qué documentos llevar antes de viajar a la municipalidad y poder pedir "
        "hora sin usar internet.",
        "Expectativas del resultado: salir con la licencia renovada en una sola visita.",
        "Expectativas del proceso: que le expliquen los exámenes y que la atiendan sentada.",
        "Relación actual con el servicio: llama por teléfono, pero nadie contesta en la tarde; "
        "dos veces volvió a su casa sin renovar porque le faltaba un certificado.",
    ]),
    ("Seguimiento", [
        f"Las dudas sobre este perfil se envían a la encargada (RUT {RUT_SIN_PUNTOS}).",
    ]),
]
TABLA = [("Dimensión", "Hallazgo"),
         ("Canal preferido", "Teléfono y atención presencial"),
         ("Dolor principal", "Viajes perdidos por documentos que faltan")]


def markdown() -> str:
    partes = ["# Perfil de persona usuaria", f"_{AVISO}_"]
    for i, (titulo, parrafos) in enumerate(SECCIONES):
        partes.append(f"## {titulo}")
        partes.extend(parrafos)
        if i == 1:
            partes.append("\n".join([f"| {TABLA[0][0]} | {TABLA[0][1]} |", "| --- | --- |",
                                     *(f"| {a} | {b} |" for a, b in TABLA[1:])]))
    return "\n\n".join(partes) + "\n"


def docx(ruta: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_heading("Perfil de persona usuaria", level=1)
    doc.add_paragraph(AVISO)
    for i, (titulo, parrafos) in enumerate(SECCIONES):
        doc.add_heading(titulo, level=2)
        for p in parrafos:
            doc.add_paragraph(p)
        if i == 1:
            tabla = doc.add_table(rows=len(TABLA), cols=2)
            for fila, valores in zip(tabla.rows, TABLA, strict=True):
                for celda, valor in zip(fila.cells, valores, strict=True):
                    celda.text = valor
    doc.save(ruta)


def pdf(ruta: Path) -> None:
    """
    Una sección por página. cupsfilter (macOS) convierte texto plano a PDF con capa de texto y
    corta la página en cada salto de página («\\f»); HTML no lo convierte.
    """
    paginas = []
    for i, (titulo, parrafos) in enumerate(SECCIONES):
        lineas = ["Perfil de persona usuaria", AVISO, ""] if i == 0 else []
        lineas += [titulo.upper(), ""]
        for parrafo in parrafos:
            lineas += [*textwrap.wrap(parrafo, 78), ""]
        if i == 1:
            lineas += [f"{a:<20} {b}" for a, b in TABLA]
        paginas.append("\n".join(lineas))
    with tempfile.TemporaryDirectory() as tmp:
        fuente = Path(tmp) / "perfil.txt"
        fuente.write_text("\n\f".join(paginas) + "\n", encoding="utf-8")
        salida = subprocess.run(["/usr/sbin/cupsfilter", "-m", "application/pdf", str(fuente)],
                                capture_output=True, check=True).stdout
    ruta.write_bytes(salida)


def escaneado(ruta: Path) -> None:
    """Una página que es solo una imagen con texto dibujado: no tiene capa de texto."""
    from PIL import Image, ImageDraw

    imagen = Image.new("RGB", (1240, 1754), "white")  # A4 a 150 dpi
    dibujo = ImageDraw.Draw(imagen)
    for i, linea in enumerate(["Perfil de persona usuaria (escaneado)", AVISO, *SECCIONES[1][1]]):
        dibujo.text((80, 120 + 40 * i), linea, fill="black")
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "escaneado.png"
        imagen.save(png)
        subprocess.run(["sips", "-s", "format", "pdf", str(png), "--out", str(ruta)],
                       capture_output=True, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    (CARPETA / "perfil.md").write_text(markdown(), encoding="utf-8")
    docx(CARPETA / "perfil.docx")
    pdf(CARPETA / "perfil.pdf")
    escaneado(CARPETA / "escaneado.pdf")
    (CARPETA / "no-es-pdf.pdf").write_text(f"Esto es texto plano con extensión .pdf.\n{AVISO}\n", encoding="utf-8")
    for ruta in sorted(CARPETA.glob("*.*")):
        if ruta.suffix != ".py":
            print(f"{ruta.name:15} {ruta.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
