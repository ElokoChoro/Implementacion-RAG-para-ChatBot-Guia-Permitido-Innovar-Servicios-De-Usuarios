"""
Respuesta a una pregunta sobre la guía, con citas y nivel de confianza.

  1. Recuperación: `recuperar()` con el reranker deja los TOP_K fragmentos, cada
     uno con un puntaje entre 0 y 1.
  2. Umbral: se descartan los fragmentos con puntaje bajo UMBRAL. Si no queda
     ninguno, la guía no responde la pregunta y se contesta «No encuentro esa
     información en la guía.» sin llamar al LLM.
  3. Generación: el LLM (Ollama u otro servidor, según PROVEEDOR_LLM) redacta
     la respuesta solo con esos fragmentos, citando la línea «fuente:» de cada
     uno (prompts.py). Todavía puede rechazar la pregunta si los fragmentos no
     la responden.

Las fuentes de la respuesta salen de los fragmentos, no del texto del LLM, y la
confianza sale del mejor puntaje del reranker (CONFIANZA_MEDIA, CONFIANZA_ALTA).
El umbral, la llamada al LLM y la forma de la respuesta son los mismos de
sugerir.py: están en flujo.py. Cada respuesta deja en el log cuánto tardaron la
recuperación y el LLM, y cuántos tokens usó el LLM (registro.py).
La forma de la respuesta (`Respuesta`) está en contrato.py.

Prueba rápida, desde backend/ (el servidor del LLM corriendo con el modelo de config.LLM):
    python -m app.rag.generar "¿Qué es un mapa de momentos críticos?" --etapa 7
    python -m app.rag.generar "¿Cuánto presupuesto se necesita?" --json
"""
from __future__ import annotations

import argparse
import json
import logging
import time

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.schema import NodeWithScore

from app.rag import registro
from app.rag.contrato import Respuesta
from app.rag.flujo import SIN_LLM, Tokens, armar_respuesta, chat, contexto, sobre_el_umbral
from app.rag.prompts import MENSAJE_NO_ENCONTRADA, SISTEMA, SUGERENCIA, USUARIO, texto_etapa
from app.rag.recuperar import recuperar

log = logging.getLogger("app.rag.generar")  # no __name__: con python -m vale «__main__»


def _generar(pregunta: str, etapa: int | None, nodos: list[NodeWithScore]) -> tuple[str, Tokens]:
    """
    Texto del LLM con el prompt y los fragmentos, y los tokens que usó.

    RuntimeError si el servidor del LLM no responde.
    """
    return chat([
        ChatMessage(role=MessageRole.SYSTEM, content=SISTEMA),
        ChatMessage(role=MessageRole.USER, content=USUARIO.format(
            etapa=texto_etapa(etapa), contexto=contexto(nodos), pregunta=pregunta)),
    ])


def responder(pregunta: str, etapa: int | None = None, filtrar_etapa: bool = False) -> Respuesta:
    """
    Responde `pregunta` usando solo la guía.

    `etapa` (1 a 7) se le indica al LLM para resolver preguntas ambiguas; con
    `filtrar_etapa=True`, además, solo se buscan fragmentos de esa etapa.
    Lanza RuntimeError si el LLM local no está disponible.
    """
    t0 = time.time()
    # El umbral está calibrado sobre el puntaje del reranker, así que siempre se usa.
    nodos, mejor = sobre_el_umbral(recuperar(pregunta, etapa if filtrar_etapa else None, usar_reranker=True),
                                   pregunta)
    tiempos = {"etapa": etapa, "filtrar_etapa": filtrar_etapa, "largo_pregunta": len(pregunta), "mejor": mejor,
               "fragmentos": len(nodos), "t_recuperacion_s": round(time.time() - t0, 1)}

    if not nodos:  # ningún fragmento es relevante: no se llama al LLM
        log.info(registro.campos(**tiempos, llm="no", **SIN_LLM.campos(), encontrada=False))
        return armar_respuesta(f"{MENSAJE_NO_ENCONTRADA} {SUGERENCIA}", nodos, mejor, t0)

    t1 = time.time()
    texto, uso = _generar(pregunta, etapa, nodos)
    r = armar_respuesta(texto, nodos, mejor, t0)
    log.info(registro.campos(**tiempos, t_llm_s=round(time.time() - t1, 1), **uso.campos(),
                             encontrada=r.encontrada))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta")
    ap.add_argument("--etapa", type=int, help="etapa del proyecto (1-7), se le indica al LLM")
    ap.add_argument("--filtrar-etapa", action="store_true", help="busca solo fragmentos de esa etapa")
    ap.add_argument("--json", action="store_true", help="salida con la forma del contrato")
    args = ap.parse_args()
    registro.configurar()

    r = responder(args.pregunta, args.etapa, args.filtrar_etapa)
    if args.json:
        print(json.dumps(r.a_dict(), ensure_ascii=False, indent=2))
        return
    print(f"\n{r.resultado}\n")
    puntaje = f"{r.puntaje:.3f}" if r.puntaje is not None else "—"
    print(f"— encontrada: {r.encontrada} · confianza: {r.confianza or '—'} · mejor puntaje: {puntaje}"
          f" · {r.latencia_s} s · {r.modelo} · prompt {r.version_prompt}")
    for f in r.fuentes:
        print(f"   · [{f['puntaje']:.3f}] {f['fuente']}")


if __name__ == "__main__":
    main()
