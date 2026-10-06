"""
Limpieza del texto extraído por Docling (`ingesta/limpieza.py`) y el corpus v3 que deja.

Las reglas se prueban con trozos tal como los entrega Docling; el corpus, con el
archivo versionado: no hace falta Docling ni el PDF.
"""
from __future__ import annotations

import json
import re

import pytest

from app.rag import config
from app.rag.guia import HERRAMIENTAS
from ingesta.limpieza import CORRECCIONES, limpiar, repite, unir_cortes

RUTA_V2 = config.RAIZ / "data" / "corpus" / "v2" / "paginas.jsonl"
RUTA_V3 = config.RAIZ / "data" / "corpus" / "v3" / "paginas.jsonl"
PAGINA_SIN_REGLAS = 20  # no es de herramienta ni tiene CORRECCIONES


def _corpus(ruta) -> dict[int, dict]:
    with ruta.open(encoding="utf-8") as f:
        return {r["pagina_inicio"]: r for r in map(json.loads, f)}


def test_une_palabras_en_mayuscula_cortadas_con_guion() -> None:
    assert unir_cortes("HABILITA- CIÓN Y EX- PECTATIVAS") == "HABILITACIÓN Y EXPECTATIVAS"
    # En minúscula es un inciso de la guía, no un corte
    inciso = "con la Subsecretaría de Hacienda- desarrollaron"
    assert unir_cortes(inciso) == inciso


def test_une_parrafos_partidos() -> None:
    texto = "Los formatos buscan ser una\n\norientación y un apoyo.\n\nOtra idea."
    assert limpiar(texto, PAGINA_SIN_REGLAS) == "Los formatos buscan ser una orientación y un apoyo.\n\nOtra idea."


def test_titulo_partido_vuelve_a_ser_parrafo() -> None:
    texto = "## El desempeño es clave en la experiencia\n\nusuaria. Por eso importa."
    assert limpiar(texto, PAGINA_SIN_REGLAS) == "El desempeño es clave en la experiencia usuaria. Por eso importa."


@pytest.mark.parametrize("texto", [
    "Termina con punto.\n\nminúscula al inicio",  # el primero cierra la oración
    "| tabla | elementos |\n\nvisuales)",  # una tabla no se une con el párrafo siguiente
])
def test_no_une_parrafos_completos(texto: str) -> None:
    assert limpiar(texto, PAGINA_SIN_REGLAS) == texto


def test_numera_los_pasos_de_como_se_usa() -> None:
    texto = ("Intro.\n\n## ¿CÓMO SE USA?\n\n1\n\nSeleccionen un rol.\n\n## 2\n\n## Definan el foco.\n\n"
             "Ejemplo: algo.\n\n## ¿QUÉ RESULTADOS GENERA?\n\nFin.")
    assert limpiar(texto, PAGINA_SIN_REGLAS) == (
        "Intro.\n\n## ¿CÓMO SE USA?\n\n1. Seleccionen un rol.\n\n2. Definan el foco.\n\nEjemplo: algo.\n\n"
        "## ¿QUÉ RESULTADOS GENERA?\n\nFin.")


def test_quita_numeros_y_letras_sueltas() -> None:
    texto = "30\n\n## ORIENTACIÓN\n\nPÁG.\n\n## C\n\n## CO-CREACIÓN\n\nModelo.\n\nPÁG 56\n\n111"
    assert limpiar(texto, PAGINA_SIN_REGLAS) == "## ORIENTACIÓN\n\n## CO-CREACIÓN\n\nModelo.\n\nPÁG 56"


def test_quita_llamadas_a_nota_y_numero_de_pagina_en_figura() -> None:
    nota = "mejorar dicha experiencia 1 . La implementación"
    assert limpiar(nota, PAGINA_SIN_REGLAS) == "mejorar dicha experiencia. La implementación"
    assert limpiar("[Figura] RECORRIDO PROPÓSITO 35", 35) == "[Figura] RECORRIDO PROPÓSITO"


def test_titulo_de_herramienta_desde_el_indice() -> None:
    texto = "## PRODUCCIÓN DE HERRAMIENTA\n\n## MAPA DE COVALOR\n\n## ¿PARA QUÉ SIRVE?\n\nPermite visualizar."
    assert limpiar(texto, 82) == (
        "## HERRAMIENTA\n\n## MAPA DE CO-PRODUCCIÓN VALOR\n\n## ¿PARA QUÉ SIRVE?\n\nPermite visualizar.")
    # Si antes del «¿Para qué sirve?» hay algo que no es título, no se toca
    con_texto = "Un párrafo.\n\n## MAPA DE COVALOR\n\n## ¿PARA QUÉ SIRVE?\n\nPermite visualizar."
    assert limpiar(con_texto, 82) == con_texto


def test_une_filas_partidas_de_la_lista_de_actividades_base() -> None:
    tabla = ("| PERSONAS | Describir a las personas | pág. |\n| - | - | - |\n|  | institucionales. | 140 |\n"
             "| MARCO | Explorar la institucionalidad | pág. |\n| INSTITUCIONAL | vigente. | 112 |")
    assert limpiar(tabla, 25) == ("| PERSONAS | Describir a las personas institucionales. | pág. 140 |\n| - | - | - |\n"
                                  "| MARCO INSTITUCIONAL | Explorar la institucionalidad vigente. | pág. 112 |")


def test_no_une_el_encabezado_pag() -> None:
    tabla = "| LISTA DE ACTIVIDADES | PÁG. |\n| - | - |\n| PERSONAS Describir | 140 |"
    assert limpiar(tabla, 34) == tabla


def test_figura_que_repite_la_tabla() -> None:
    tabla = ("| LISTA DE ACTIVIDADES | PÁG. |\n| - | - |\n"
             "| INVESTIGACIÓN Diseñar y ejecutar la investigación de las personas usuarias | 108 |\n"
             "| PERSONAS Describir a las personas usuarias de los servicios institucionales | 140 |")
    figura = ("[Figura] LISTA DE ACTIVIDADES PÁG. INVESTIGACIÓN Diseñar y ejecutar la investigación de las "
              "personas usuarias 108 PERSONAS Describir a las personas usuarias de los servicios 140 INVESTIGA- CIÓN")
    assert repite(figura, tabla)
    assert not repite("[Figura] OBJETIVOS DE LA PERSONA USUARIA ROL INFLUENCIA NECESIDADES ACTOR", tabla)


def test_correccion_que_ya_no_aparece_avisa() -> None:
    with pytest.raises(ValueError, match="CORRECCIONES"):
        limpiar("texto sin la errata", 9)


def test_correcciones_tienen_antes_y_despues_distintos() -> None:
    for pagina, pares in CORRECCIONES.items():
        assert all(antes != despues for antes, despues in pares), pagina


# ---- Corpus v3 ------------------------------------------------------------------

def test_v3_tiene_las_mismas_paginas_y_metadatos_que_v2() -> None:
    # La limpieza cambia el texto, no qué se indexa ni cómo se cita.
    v2, v3 = _corpus(RUTA_V2), _corpus(RUTA_V3)
    assert v2.keys() == v3.keys()
    for n in v2:
        assert {k: v for k, v in v3[n].items() if k not in ("texto", "version_corpus")} == \
               {k: v for k, v in v2[n].items() if k not in ("texto", "version_corpus")}, n
        assert v3[n]["version_corpus"] == "v3"


def test_v3_sin_restos_del_diseno() -> None:
    for n, r in _corpus(RUTA_V3).items():
        texto = r["texto"]
        assert not re.search(r"[A-ZÁÉÍÓÚÑ]{2,}- [A-ZÁÉÍÓÚÑ]{2,}", texto), n
        assert not re.search(r"^(?:## )?\d{1,3}$", texto, re.M), n
        assert not re.search(r"^(?:## )?[A-ZÑ]$", texto, re.M), n


def test_v3_titulo_de_cada_herramienta() -> None:
    corpus = _corpus(RUTA_V3)
    for pagina, nombre in HERRAMIENTAS:
        assert corpus[pagina]["texto"].startswith(f"## HERRAMIENTA\n\n## {nombre.upper()}\n\n"), pagina


def test_v3_paginas_52_y_53_sin_la_figura_de_muestra() -> None:
    # Su figura reproduce las págs. 58-59 y 78: ese texto no puede citarse como de las págs. 52 y 53.
    corpus = _corpus(RUTA_V3)
    assert "[Figura]" not in corpus[52]["texto"] + corpus[53]["texto"]
