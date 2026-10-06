"""
Limpieza del texto que extrae Docling, para el corpus v3 en adelante.

Docling deja restos del diseño de la guía que ensucian los fragmentos: palabras
cortadas con guion en los diagramas («HABILITA- CIÓN»), títulos de herramienta
en desorden («## MAPA DE COVALOR» + «## PRODUCCIÓN DE HERRAMIENTA»), párrafos
partidos en dos, números de paso en un párrafo aparte, figuras que repiten una
tabla y páginas de muestra leídas como si fueran texto de la página. Cada regla
corrige un tipo de problema en todas las páginas donde aparece; lo poco que no
sigue un patrón va en CORRECCIONES, contrastado con el texto del PDF.

La limpieza va en el código y no a mano sobre el corpus ni sobre la base: así
se aplica igual cada vez que se regenera el corpus, y los embeddings se
calculan con el texto limpio. ingesta/corpus.py la aplica a cada página; el
corpus v2 se generó sin ella.

Para ver una página antes y después, desde la raíz:

    python -m ingesta.corpus --ver 128 --crudo
    python -m ingesta.corpus --ver 128

Las reglas no dependen de Docling y se prueban en backend/tests/test_limpieza.py.
"""
from __future__ import annotations

import re

from app.rag.guia import HERRAMIENTAS

# En «Cada actividad incluye» (p. 52) y «Para cada herramienta podrán encontrar»
# (p. 53), la figura es una página de muestra de la guía con sus partes marcadas
# (a, b, c, d). Docling lee todo su texto, que es el de la actividad Adopción
# (págs. 58-59) y el de la Ficha de contexto institucional (p. 78): sin esta
# regla, esas páginas aparecen como fuente de contenido que no es suyo.
FIGURAS_DE_MUESTRA = {52, 53}

# Texto mal extraído que no sigue un patrón, por página: (como sale, como dice el PDF).
CORRECCIONES = {
    # El inciso «—sobre todo—» pierde la raya de cierre y el salto de línea.
    9: [("-sobre todousarla", "-sobre todo- usarla")],
    # URLs de las notas al pie, cortadas por el salto de línea del PDF.
    14: [("https://satisfaccion.gob.cl/\n\nsistema-de-calidad-de-servi-\n\ncio-y-experiencia-usuaria",
          "https://satisfaccion.gob.cl/sistema-de-calidad-de-servicio-y-experiencia-usuaria")],
    15: [("https://escuela. innovadorespublicos.cl", "https://escuela.innovadorespublicos.cl")],
    # La última celda de la tabla de claves perceptuales queda fuera de la tabla.
    65: [("colores, elementos | Infografías y material audiovisual publicados |\n\nvisuales)",
          "colores, elementos visuales) | Infografías y material audiovisual publicados |")],
    # Texto espaciado del plano del servicio de FONASA.
    124: [("USUAR IO", "USUARIO"), ("L ÍNEA DE VI S I B I L IDAD", "LÍNEA DE VISIBILIDAD"),
          ("L ÍNEA DE INTERACCIÓN", "LÍNEA DE INTERACCIÓN")],
}

_MAYUS = "A-ZÁÉÍÓÚÜÑ"
_LETRA_FINAL = re.compile(r"[^\W\d_],?$")  # termina en letra o en coma: la oración sigue
_INICIO_MINUSCULA = re.compile(r"[a-záéíóúüñ]")
_NUMERO_SUELTO = re.compile(r"(?:## )?(\d{1,3})")
_TITULO_PASOS = "## ¿CÓMO SE USA?"


def unir_cortes(texto: str) -> str:
    """«HABILITA- CIÓN» → «HABILITACIÓN»: palabras en mayúscula cortadas en dos líneas de un diagrama."""
    return re.sub(rf"([{_MAYUS}]{{2,}})- ([{_MAYUS}]{{2,}})", r"\1\2", texto)


def _palabras(texto: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]{3,}", texto.lower()))


def repite(figura: str, resto: str) -> bool:
    """
    La figura solo repite el texto de la página (90 % de sus palabras o más).

    En las listas de actividades de los propósitos (págs. 30 y 42), Docling lee
    la lista dos veces: como tabla y como el texto de la imagen. En la p. 104,
    el diagrama de valor solo repite las palabras del párrafo que lo explica.
    """
    palabras = _palabras(unir_cortes(figura)) - {"figura"}
    return len(palabras) >= 10 and len(palabras & _palabras(unir_cortes(resto))) >= 0.9 * len(palabras)


def _unir_parrafos(bloques: list[str]) -> list[str]:
    """
    Une el párrafo que quedó cortado en dos: el primero termina sin puntuación
    y el siguiente empieza con minúscula («buscan ser una» + «orientación y un
    apoyo»). Si el primero salió como título («## El desempeño… de la
    experiencia» + «usuaria. Por eso…»), deja de serlo.
    """
    unidos: list[str] = []
    for bloque in bloques:
        previo = unidos[-1] if unidos else ""
        if (previo and not previo.startswith("|") and _LETRA_FINAL.search(previo)
                and _INICIO_MINUSCULA.match(bloque)):
            unidos[-1] = f"{previo.removeprefix('## ')} {bloque}"
        else:
            unidos.append(bloque)
    return unidos


def _numerar_pasos(bloques: list[str]) -> list[str]:
    """
    En «¿Cómo se usa?», el número de cada paso sale en un párrafo aparte («3» o
    «## 3»): se une al texto del paso («3. Identifiquen…»).
    """
    if _TITULO_PASOS not in bloques:
        return bloques
    salida = bloques[:bloques.index(_TITULO_PASOS) + 1]
    pendientes = bloques[len(salida):]
    while pendientes:
        bloque = pendientes.pop(0)
        if bloque.startswith("## ¿"):  # empieza otra sección
            salida += [bloque, *pendientes]
            break
        numero = _NUMERO_SUELTO.fullmatch(bloque)
        siguiente = pendientes[0].removeprefix("## ") if pendientes else ""
        if numero and re.match(rf"[{_MAYUS}¿]", siguiente):
            salida.append(f"{numero.group(1)}. {siguiente}")
            pendientes.pop(0)
        else:
            salida.append(bloque)
    return salida


def _es_ruido(bloque: str) -> bool:
    """
    Párrafos que no dicen nada fuera del diseño de la página: números sueltos
    (de página, de paso o las páginas de la tabla de la p. 19), «PÁG.» sin
    número y las letras del glosario («## C»).
    """
    return bool(_NUMERO_SUELTO.fullmatch(bloque) or bloque == "PÁG."
                or re.fullmatch(rf"(?:## )?[{_MAYUS}]", bloque))


def _unir_filas_pagina(bloque: str) -> str:
    """
    En la lista de actividades base (p. 25), cada fila de la tabla sale partida
    en dos: «| PERSONAS | Describir a las personas usuarias de los servicios |
    pág. |» y «| | institucionales. | 140 |». Se unen celda a celda.
    """
    if not bloque.startswith("|"):
        return bloque
    filas = [[c.strip() for c in linea.strip().strip("|").split("|")] for linea in bloque.split("\n")]
    salida, i = [], 0
    while i < len(filas):
        fila = filas[i]
        j = i + 1
        if j < len(filas) and set(filas[j]) == {"-"}:  # separador del encabezado
            j += 1
        if fila[-1] == "pág." and j < len(filas) and len(filas[j]) == len(fila) and filas[j][-1].isdigit():
            unida = [" ".join(x for x in par if x) for par in zip(fila, filas[j], strict=True)]
            salida += [unida] + filas[i + 1:j]
            i = j + 1
        else:
            salida.append(fila)
            i += 1
    return "\n".join("| " + " | ".join(f) + " |" for f in salida)


def _titulo_herramienta(bloques: list[str], n: int) -> list[str]:
    """
    En la primera página de cada herramienta, el título sale en desorden porque
    en el PDF está en dos columnas junto a la palabra «HERRAMIENTA» («## MAPA DE
    COVALOR» + «## PRODUCCIÓN DE HERRAMIENTA», p. 82). Se reemplaza por el
    nombre del índice de herramientas (HERRAMIENTAS de guia.py).
    """
    nombre = dict(HERRAMIENTAS).get(n)
    fin = bloques.index("## ¿PARA QUÉ SIRVE?") if "## ¿PARA QUÉ SIRVE?" in bloques else None
    if not nombre or not fin or not all(b.startswith("## ") for b in bloques[:fin]):
        return bloques
    return ["## HERRAMIENTA", f"## {nombre.upper()}", *bloques[fin:]]


def limpiar(texto: str, n: int) -> str:
    """Aplica a la página `n` las CORRECCIONES y las reglas de limpieza, en orden."""
    for antes, despues in CORRECCIONES.get(n, []):
        if antes not in texto:  # Docling cambió: hay que revisar la corrección contra el PDF
            raise ValueError(f"Pág. {n}: no aparece «{antes}». Revisa CORRECCIONES en ingesta/limpieza.py "
                             "contra el PDF.")
        texto = texto.replace(antes, despues)
    texto = unir_cortes(texto)
    texto = re.sub(r"(\w) [1-9] \.", r"\1.", texto)  # llamada a nota al pie: «experiencia 1 .»
    texto = re.sub(rf"^(\[Figura\] .+) {n}$", r"\1", texto, flags=re.M)  # n.º de página al final de la figura
    bloques = [b.strip() for b in texto.split("\n\n") if b.strip()]
    bloques = _numerar_pasos(_unir_parrafos(bloques))
    bloques = [_unir_filas_pagina(b) for b in bloques if not _es_ruido(b)]
    return "\n\n".join(_titulo_herramienta(bloques, n))
