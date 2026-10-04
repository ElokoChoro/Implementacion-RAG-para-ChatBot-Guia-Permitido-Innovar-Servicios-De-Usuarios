"""
Próximos pasos para un equipo que está en una etapa del Propósito 1, con citas
a la guía. Es lo que debe devolver `POST /ia/sugerir-proximos-pasos`.

  1. Recuperación: una consulta fija por etapa (consulta()), filtrada por el
     metadato `etapa`, con el reranker. No usa el texto del proyecto: así la
     búsqueda no depende de lo que escriba el equipo y no se puede desviar con
     él. Con el filtro, los 4 fragmentos son de la actividad de la etapa en las
     7 etapas; sin él, en 5 de 7 se cuela otra actividad (eval/README.md).
  2. Umbral: se descartan los fragmentos bajo UMBRAL, igual que en generar.py.
  3. Generación: el LLM recibe el contexto de la etapa (guia.py), los fragmentos
     y lo que el equipo registró del proyecto (`contexto` y `datos_etapa`), y
     redacta con el formato de prompts_etapa.py.
  4. Citas: se corrige la forma de las que no copian exacto una línea «fuente:»
     del prompt (ajustar_citas).

La respuesta tiene la forma de `Respuesta` (generar.py); las fuentes y la
confianza salen de los fragmentos y del reranker, no del texto del LLM.

Prueba rápida, desde backend/ (Ollama corriendo con el modelo de config.LLM):
    python -m app.rag.sugerir 1
    python -m app.rag.sugerir 7 --contexto "Servicio de licencias médicas" \\
        --datos '{"mapa_momentos_criticos": "pendiente"}' --json
    python -m app.rag.sugerir 4 --ver-prompt   # muestra el prompt sin llamar al LLM
    python -m app.rag.sugerir 4 --ver-consulta # solo la consulta de la etapa, sin modelos
"""
from __future__ import annotations

import argparse
import json
import re
import time

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle

from app.rag import config, guia
from app.rag.generar import Respuesta, _contexto, _fuente, chat, confianza
from app.rag.prompts import MENSAJE_NO_ENCONTRADA
from app.rag.prompts_etapa import (
    PROYECTO_VACIO,
    SIN_FRAGMENTOS,
    SISTEMA_ETAPA,
    USUARIO_ETAPA,
    VERSION_PROMPT_ETAPA,
    texto_etapa,
)
from app.rag.recuperar import recuperar


def _a_texto(valor) -> str:
    """
    Texto legible de lo que envía la plataforma. Un diccionario plano va como
    lista «- clave: valor» («mapa_problema_completo» → «mapa problema completo»):
    gemma3:4b relaciona mejor esa lista que un JSON con la herramienta de la guía.
    """
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, dict) and all(isinstance(v, (str, int, float, bool)) or v is None
                                       for v in valor.values()):
        return "\n".join(f"- {str(k).replace('_', ' ')}: {v}" for k, v in valor.items())
    return json.dumps(valor, ensure_ascii=False, indent=1)


def limpiar_citas(texto: str) -> str:
    """
    Quita lo que el LLM copia del formato: el prefijo «fuente:» o «cita:» dentro de los
    corchetes y una línea que repite la plantilla («una o dos frases [fuente].»).
    """
    texto = re.sub(r"^[ \t]*una o dos frases \[fuente\]\.[ \t]*\n+", "", texto,
                   flags=re.IGNORECASE | re.MULTILINE)
    texto = re.sub(r"(\*\*Qué busca esta etapa:\*\*)[ \t]*una o dos frases \[fuente\]\.[ \t]*\n+",
                   r"\1 ", texto, flags=re.IGNORECASE)
    return re.sub(r"\[\s*(?:fuente|cita)\s*:\s*", "[", texto, flags=re.IGNORECASE)


def _ajustar_cita(cita: str, fuentes: set[str]) -> str:
    """Una cita, cambiada por la única fuente del prompt que calza con su sección y página."""
    cita = cita.strip()
    if cita in fuentes:
        return cita
    # Sobra algo después de una fuente válida: «…, p. 128, paso 1».
    for f in fuentes:
        if cita.startswith(f):
            return f
    # Falta la herramienta («Investigación, p. 110» por «Investigación › Plan…, p. 110») o la
    # actividad («Plan…, p. 118» por «Medición › Plan…, p. 118»).
    m = re.match(r"(.+?), p\. (\d+(?:-\d+)?)", cita)
    nombre, pagina = (m.group(1), m.group(2)) if m else (cita, None)
    candidatas = [f for f in fuentes
                  if (f.startswith(nombre) or f"› {nombre}," in f)
                  and (pagina is None or f.endswith(f", p. {pagina}"))]
    return candidatas[0] if len(candidatas) == 1 else cita


def ajustar_citas(texto: str, fuentes: set[str]) -> str:
    """
    Corrige la forma de las citas que no copian exacto una línea «fuente:».

    Con gemma3:4b, en la evaluación todas las citas apuntaban a una sección y una
    página que estaban en el prompt, pero un tercio no copiaba la línea exacta:
    agregaba «, paso 2» u omitía la herramienta. Solo se cambia la cita
    cuando una única fuente del prompt calza con su sección y página; si no, queda
    como la escribió el LLM.
    """
    def arreglar(m: re.Match) -> str:
        return "[" + "; ".join(_ajustar_cita(c, fuentes) for c in m.group(1).split(";")) + "]"
    return re.sub(r"\[([^\[\]]+)\]", arreglar, texto)


def texto_proyecto(contexto: str | dict | None, datos_etapa: dict | None) -> str:
    """
    Lo que el equipo registró del proyecto, listo para ir entre <proyecto> y </proyecto>.

    Los «<» y «>» se cambian por «‹» y «›» para que el texto no pueda cerrar la
    etiqueta y hacerse pasar por guía, y se corta en MAX_CARACTERES_PROYECTO para
    no salirse de la ventana de contexto del LLM.
    """
    partes = []
    if contexto:
        partes.append(f"Contexto del proyecto:\n{_a_texto(contexto)}")
    if datos_etapa:
        partes.append(f"Avance registrado en esta etapa:\n{_a_texto(datos_etapa)}")
    texto = "\n\n".join(partes).replace("<", "‹").replace(">", "›")
    if len(texto) > config.MAX_CARACTERES_PROYECTO:
        texto = texto[:config.MAX_CARACTERES_PROYECTO].rstrip() + " […]"
    return texto or PROYECTO_VACIO


def consulta(etapa: int) -> str:
    """Consulta con que se recuperan los fragmentos de la etapa. ValueError si no existe."""
    e = guia.etapa(etapa)
    if e is None:
        raise ValueError(f"La etapa debe ser un número de 1 a {len(guia.PROPOSITOS[1].etapas)}.")
    nombres = ", ".join(nombre for _, nombre in e.herramientas)
    return (f"Actividad de {e.actividad}: en qué consiste, cuándo desarrollarla y cómo "
            f"se usa paso a paso {nombres}")


def mensajes(etapa: int, nodos: list[NodeWithScore], proyecto: str) -> list[ChatMessage]:
    """Mensajes de sistema y de usuario del asistente por etapa."""
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=SISTEMA_ETAPA),
        ChatMessage(role=MessageRole.USER, content=USUARIO_ETAPA.format(
            etapa=texto_etapa(etapa), proyecto=proyecto, contexto=_contexto(nodos))),
    ]


def fuentes_prompt(nodos: list[NodeWithScore]) -> set[str]:
    """Líneas «fuente:» de los fragmentos que recibe el LLM."""
    return {n.node.metadata["fuente"] for n in nodos}


def fragmentos(etapa: int) -> tuple[list[NodeWithScore], float | None]:
    """Fragmentos de la etapa que pasan el umbral y el mejor puntaje del reranker."""
    q = consulta(etapa)
    nodos = recuperar(q, etapa, usar_reranker=True)
    mejor = round(float(nodos[0].score), 3) if nodos else None
    nodos = SimilarityPostprocessor(similarity_cutoff=config.UMBRAL).postprocess_nodes(
        nodos, query_bundle=QueryBundle(q))
    return nodos, mejor


def sugerir(etapa: int, contexto: str | dict | None = None,
            datos_etapa: dict | None = None) -> Respuesta:
    """
    Próximos pasos para la etapa `etapa` (1 a 7), adaptados al proyecto.

    `contexto` y `datos_etapa` son los campos que ya envía la plataforma: texto o
    diccionario con lo que el equipo registró. ValueError si la etapa no existe;
    RuntimeError si el LLM local no está disponible.
    """
    t0 = time.time()
    consulta(etapa)  # valida la etapa antes de cargar modelos
    nodos, mejor = fragmentos(etapa)
    if not nodos:
        return Respuesta(resultado=SIN_FRAGMENTOS, encontrada=False, confianza=None,
                         version_prompt=VERSION_PROMPT_ETAPA, puntaje=mejor,
                         latencia_s=round(time.time() - t0, 1))

    texto = limpiar_citas(chat(mensajes(etapa, nodos, texto_proyecto(contexto, datos_etapa))))
    texto = ajustar_citas(texto, fuentes_prompt(nodos))
    encontrada = not texto.startswith(MENSAJE_NO_ENCONTRADA)
    return Respuesta(
        resultado=texto,
        encontrada=encontrada,
        confianza=confianza(mejor) if encontrada else None,
        fuentes=[_fuente(n) for n in nodos] if encontrada else [],
        version_prompt=VERSION_PROMPT_ETAPA,
        puntaje=mejor,
        latencia_s=round(time.time() - t0, 1),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("etapa", type=int, help="etapa del proyecto (1-7)")
    ap.add_argument("--contexto", help="contexto del proyecto (texto)")
    ap.add_argument("--datos", help="datos de la etapa, en JSON")
    ap.add_argument("--json", action="store_true", help="salida con la forma del contrato")
    ap.add_argument("--ver-prompt", action="store_true", help="muestra el prompt sin llamar al LLM")
    ap.add_argument("--ver-consulta", action="store_true", help="muestra la consulta de la etapa, sin modelos")
    args = ap.parse_args()
    datos = json.loads(args.datos) if args.datos else None

    if args.ver_consulta:
        print(consulta(args.etapa))
        return

    if args.ver_prompt:
        nodos, _ = fragmentos(args.etapa)
        for m in mensajes(args.etapa, nodos, texto_proyecto(args.contexto, datos)):
            print(f"===== {m.role.value}\n{m.content}\n")
        return

    r = sugerir(args.etapa, args.contexto, datos)
    if args.json:
        print(json.dumps(r.a_dict(), ensure_ascii=False, indent=2))
        return
    print(f"\n{r.resultado}\n")
    puntaje = f"{r.puntaje:.3f}" if r.puntaje is not None else "—"
    print(f"— confianza: {r.confianza or '—'} · mejor puntaje: {puntaje} · {r.latencia_s} s"
          f" · {r.modelo} · prompt {r.version_prompt}")
    for f in r.fuentes:
        print(f"   · {f['fuente']}")


if __name__ == "__main__":
    main()
