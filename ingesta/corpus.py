"""
Paso 2 de la ingesta: convierte el JSON de Docling en el corpus versionado
data/corpus/<VERSION_CORPUS>/paginas.jsonl.

Cada línea es una página de la guía en Markdown, con los metadatos que
permiten citar («Personas › Perfil de persona usuaria, p. 148») y filtrar por
etapa. La sección, la actividad y la herramienta de cada página se deducen de
los índices de la guía (tablas SECCIONES, ACTIVIDADES y HERRAMIENTAS).

    python -m ingesta.corpus
    python -m ingesta.corpus --ver 148   # muestra cómo quedó una página

Formato de cada registro: ver data/corpus/README.md.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys

from docling_core.types.doc.document import (
    DEFAULT_EXPORT_LABELS,
    ContentLayer,
    DocItemLabel,
    DoclingDocument,
    PictureItem,
    TextItem,
)

from app.rag import config
from ingesta.extraer import RAIZ, SALIDA as ENTRADA

# Páginas que entran al índice: los créditos (2), los prólogos (8-11), de la
# Introducción al Glosario (13-161) y «¿Cómo elaboramos esta guía?» (162-163).
# Créditos, prólogos y elaboración responden quién hizo la guía, cuándo y cómo.
# Quedan fuera la portada, los índices (4-7), las referencias, el equipo y la
# contraportada.
PAGINAS = {2, *range(8, 12), *range(13, 164)}
PALABRAS_MINIMAS = 15  # descarta portadillas casi vacías

# Los créditos (p. 2) se indexan como esta ficha y no con el texto extraído. En la
# página, la autoría está en «¿Cómo citar este libro?» y «Esta obra…», entre
# listas de nombres en mayúsculas, y el reranker no la relaciona con preguntas
# como «¿Quién es el autor de la guía?» (puntaje 0,02, bajo el UMBRAL). La ficha
# dice lo mismo que la página, nombrando «la guía» y la autoría. Si cambia la
# guía, hay que revisarla contra la p. 2.
FICHA_CREDITOS = """## Créditos de la guía

Autoría: los autores de la guía «¿Cómo podemos innovar en los servicios públicos desde la experiencia \
usuaria?» son el Laboratorio de Gobierno del Ministerio de Hacienda (Gobierno de Chile) y el \
Observatorio UX de la Universidad Tecnológica Metropolitana (UTEM). La guía surge del trabajo \
colaborativo entre ambos, es parte de la serie Permitido Innovar: Guías para transformar el Estado \
chileno y se publicó en 2025.

- Licencia: Creative Commons Atribución-NoComercial-CompartirIgual 4.0 Internacional (CC BY-NC-SA 4.0).
- Coordinación: Elisa Breull.
- Textos: Elisa Breull y Lorena Torres.
- Edición: Daniela Herrera.
- Diseño gráfico y sistematización visual: Myriam Meyer y María Eliana Devia.
- Observatorio UX UTEM: María de los Ángeles Ferrer, Erwin Aguirre y Ronald Méndez.
- Equipo Laboratorio de Gobierno: Alejandra Gómez, Carlos Carrillo, Constanza Jeldres, Constanza \
Pérez, Daniela Herrera, Eduardo Navarro, Elisa Breull, Fran Garretón, Francisca Flores, Francisca \
Moya, Francisco Díaz, Fremberling Ramos, Giancarlo Sillerico, Javiera Miranda, Laura González, \
Lorena Torres, María Eliana Devia, Myriam Meyer, Nicolás Galvez, Octavio Cortez, Orlando Rojas, \
Pablo Bórquez, Rodrigo Silva, Sebastián Altimira, Tomás Dintrans y Víctor Toledo.
- Cómo citarla: Laboratorio de Gobierno, Gobierno de Chile y Universidad Tecnológica Metropolitana (2025)."""

# --------------------------------------------------------------------------
# Estructura de la guía, tomada de sus índices (págs. 4 a 6).
# Cada tupla es (página donde empieza, nombre). Si cambia la guía, hay que
# revisar estas tablas.
# --------------------------------------------------------------------------
SECCIONES = [
    (1, "Créditos de la guía"),
    (8, "Prólogos"),
    (10, "Innovación pública y democracia"),
    (13, "Introducción"),
    (23, "Lo primero: actividades base para la gestión de la experiencia usuaria"),
    (27, "Propósitos"),
    (28, "Propósito 1: Comprender la experiencia actual de las personas usuarias"),
    (32, "Propósito 2: Incorporar perspectiva usuaria al quehacer institucional"),
    (36, "Propósito 3: Mejorar la satisfacción con un servicio"),
    (40, "Propósito 4: Mejorar la colaboración interna para la experiencia usuaria"),
    (44, "Propósito 5: Diseñar e implementar un nuevo servicio"),
    (51, "Actividades y herramientas"),
    (158, "Glosario"),
    (162, "¿Cómo elaboramos esta guía?"),
    (164, "Referencias"),
]

ACTIVIDADES = [
    (54, "Actores"), (58, "Adopción"), (64, "Claves perceptuales"),
    (68, "Competencias"), (72, "Comunicación"), (76, "Contexto institucional"),
    (80, "Creación de valor"), (86, "Ecosistema de canales"), (90, "Estándares"),
    (94, "Experiencia modelo"), (100, "Habilitación y Expectativas"),
    (104, "Interacciones"), (108, "Investigación"), (112, "Marco Institucional"),
    (116, "Medición"), (120, "Modelo operativo"), (126, "Momentos críticos"),
    (132, "Necesidades"), (140, "Personas"), (150, "Sensibilización"),
    (154, "Vinculación"),
]

HERRAMIENTAS = sorted([
    (152, "Ficha de actividades de sensibilización"),
    (88, "Ficha de caracterización de canales"),
    (114, "Ficha de caracterización institucional"),
    (70, "Ficha de competencias para la experiencia"),
    (78, "Ficha de contexto institucional"),
    (92, "Ficha de estándares de servicio"),
    (60, "Ficha de intervenciones para la adopción"),
    (66, "Lista de claves perceptuales"),
    (56, "Mapa de actores del ecosistema del servicio"),
    (82, "Mapa de co-producción valor"),
    (102, "Mapa de expectativas"),
    (128, "Mapa de momentos críticos"),
    (142, "Mapa de perfiles de personas usuarias"),
    (134, "Mapa del problema completo"),
    (156, "Matriz de vinculación entre necesidades y servicios"),
    (148, "Perfil de persona usuaria"),
    (136, "Pilares del servicio"),
    (74, "Plan de comunicaciones del servicio"),
    (118, "Plan de evaluación de estándares de servicio"),
    (110, "Plan de investigación de experiencia usuaria"),
    (122, "Plano del servicio"),
    (106, "Viaje de la persona usuaria"),
    (96, "Viaje ideal de la persona usuaria"),
])

# Etapas de la plataforma SSP-UXLab (Propósito 1) -> actividad de la guía que
# las respalda. Las páginas de esas actividades llevan el número de etapa, que
# permite filtrar la recuperación; el resto queda sin etapa.
ETAPAS = {
    1: "Investigación", 2: "Personas", 3: "Habilitación y Expectativas",
    4: "Necesidades", 5: "Vinculación", 6: "Medición", 7: "Momentos críticos",
}


def _ultimo_que_empieza_antes(tabla, pagina):
    """Última entrada de `tabla` que empieza en `pagina` o antes (la que la contiene)."""
    candidato = None
    for inicio, nombre in tabla:
        if inicio <= pagina:
            candidato = (inicio, nombre)
    return candidato


def ubicar(pagina: int) -> dict:
    """
    Sección, actividad, herramienta y etapa de una página.

    Actividad y herramienta solo existen en «Actividades y herramientas»
    (págs. 54-157); fuera de ahí quedan vacías y la etapa en None.
    """
    seccion = _ultimo_que_empieza_antes(SECCIONES, pagina)[1]
    actividad = herramienta = ""
    if 54 <= pagina < 158:
        act = _ultimo_que_empieza_antes(ACTIVIDADES, pagina)
        actividad = act[1]
        her = _ultimo_que_empieza_antes(HERRAMIENTAS, pagina)
        # la herramienta solo cuenta si empieza dentro de la actividad actual
        if her and her[0] >= act[0]:
            herramienta = her[1]
    etapa = next((n for n, a in ETAPAS.items() if a == actividad), None)
    return {"seccion": seccion, "actividad": actividad,
            "herramienta": herramienta, "etapa": etapa}


# --------------------------------------------------------------------------
# Texto de cada página desde Docling
# --------------------------------------------------------------------------
FIGURA = "@@FIGURA@@"  # marcador temporal de cada imagen al exportar a Markdown
CAPAS = {ContentLayer.BODY, ContentLayer.FURNITURE}
# Encabezados sí (traen el nombre de la actividad o herramienta); pies de página
# no (solo tienen el número de página, que ya va en los metadatos).
ETIQUETAS = DEFAULT_EXPORT_LABELS - {DocItemLabel.PAGE_FOOTER}


def texto_figura(doc: DoclingDocument, figura: PictureItem) -> str:
    """
    Texto que Docling encontró dentro de una figura (láminas, fichas, viajes,
    listas de actividades), unido en un párrafo: viene cortado línea a línea.
    """
    partes = [it.text for it, _ in doc.iterate_items(root=figura, traverse_pictures=True,
                                                    included_content_layers=CAPAS)
              if isinstance(it, TextItem) and it.text.strip()]
    texto = re.sub(r"\s+", " ", " ".join(partes)).strip()
    return f"[Figura] {texto}" if len(texto.split()) >= 3 else ""


def texto_pagina(doc: DoclingDocument, n: int) -> str:
    """
    Markdown de la página `n`, con el texto de cada figura en su lugar.

    Muchas páginas son láminas o fichas cuyo contenido está dentro de una
    imagen; Docling reconoce ese texto y lo cuelga de la figura. Se inserta como
    un párrafo «[Figura] …» para que también se pueda recuperar.
    """
    texto = doc.export_to_markdown(page_no=n, image_placeholder=FIGURA, escape_html=False,
                                   escape_underscores=False, compact_tables=True,
                                   labels=ETIQUETAS, included_content_layers=CAPAS)
    # Cada marcador de imagen se reemplaza, en orden, por el texto de su figura.
    figuras = [it for it, _ in doc.iterate_items(page_no=n, included_content_layers=CAPAS)
               if isinstance(it, PictureItem)]
    if texto.count(FIGURA) != len(figuras):
        sys.exit(f"Pág. {n}: {texto.count(FIGURA)} marcadores y {len(figuras)} figuras")
    for figura in figuras:
        texto = texto.replace(FIGURA, texto_figura(doc, figura), 1)
    texto = html.unescape(texto)
    texto = "\n".join(linea.rstrip() for linea in texto.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def paginas(doc: DoclingDocument) -> list[dict]:
    """Registros del corpus: una página por registro, de las PAGINAS indexadas y con texto suficiente."""
    registros = []
    for n in sorted(doc.pages):
        if n not in PAGINAS:
            continue
        texto = FICHA_CREDITOS if n == 2 else texto_pagina(doc, n)
        if len(texto.split()) < PALABRAS_MINIMAS:
            continue
        ubic = ubicar(n)
        partes = [x for x in (ubic["seccion"] if not ubic["actividad"] else None,
                              ubic["actividad"], ubic["herramienta"]) if x]
        registros.append({
            "id": f"guia-p{n:03d}",
            "texto": texto,
            "fuente": f"{' › '.join(partes)}, p. {n}",
            "pagina_inicio": n,
            "pagina_fin": n,
            **ubic,
            "version_corpus": config.VERSION_CORPUS,
        })
    return registros


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ver", type=int, help="muestra la página indicada y sale")
    args = ap.parse_args()

    if not ENTRADA.exists():
        sys.exit(f"Falta {ENTRADA.relative_to(RAIZ)}. Ejecuta primero:  "
                 "python -m ingesta.extraer /ruta/a/Guia_ComoInnovar.pdf")
    registros = paginas(DoclingDocument.load_from_json(ENTRADA))

    if args.ver:
        r = next((r for r in registros if r["pagina_inicio"] == args.ver), None)
        print(f"=== {r['fuente']}  (etapa {r['etapa']})\n\n{r['texto']}" if r
              else "Página no encontrada (o fuera del rango indexado).")
        return

    config.RUTA_PAGINAS.parent.mkdir(parents=True, exist_ok=True)
    config.RUTA_PAGINAS.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in registros), encoding="utf-8")
    palabras = sum(len(r["texto"].split()) for r in registros)
    print(f"{len(registros)} páginas · {palabras:,} palabras · págs. {min(PAGINAS)}–{max(PAGINAS)} "
          f"-> {config.RUTA_PAGINAS.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
