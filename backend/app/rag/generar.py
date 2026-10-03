"""
Respuesta a una pregunta sobre la guía, con citas y nivel de confianza.

  1. Recuperación: `recuperar()` con el reranker deja los TOP_K fragmentos, cada
     uno con un puntaje entre 0 y 1.
  2. Umbral: se descartan los fragmentos con puntaje bajo UMBRAL. Si no queda
     ninguno, la guía no responde la pregunta y se contesta «No encuentro esa
     información en la guía.» sin llamar al LLM.
  3. Generación: el LLM local (Ollama) redacta la respuesta solo con esos
     fragmentos, citando la línea «fuente:» de cada uno (prompts.py). Todavía
     puede rechazar la pregunta si los fragmentos no la responden.

Las fuentes de la respuesta salen de los fragmentos, no del texto del LLM, y la
confianza sale del mejor puntaje del reranker (CONFIANZA_MEDIA, CONFIANZA_ALTA).

Prueba rápida, desde backend/ (Ollama corriendo con el modelo de config.LLM):
    python -m app.rag.generar "¿Qué es un mapa de momentos críticos?" --etapa 7
    python -m app.rag.generar "¿Cuánto presupuesto se necesita?" --json
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field

import httpx
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle
from ollama import ResponseError

from app.rag import config
from app.rag.modelos import llm
from app.rag.prompts import MENSAJE_NO_ENCONTRADA, SISTEMA, SUGERENCIA, USUARIO, VERSION_PROMPT, texto_etapa
from app.rag.recuperar import recuperar


@dataclass
class Respuesta:
    """Respuesta con la forma del contrato de `POST /ia/consultar-guia`."""

    resultado: str
    encontrada: bool
    confianza: str | None          # «alta», «media» o «baja»; None si no se encontró
    fuentes: list[dict] = field(default_factory=list)
    modelo: str = config.LLM
    version_prompt: str = VERSION_PROMPT
    modo: str = "local"
    puntaje: float | None = None   # mejor puntaje del reranker, para auditar el umbral
    latencia_s: float = 0.0

    def a_dict(self) -> dict:
        return asdict(self)


def confianza(puntaje: float) -> str:
    """Nivel de confianza según el mejor puntaje del reranker."""
    if puntaje >= config.CONFIANZA_ALTA:
        return "alta"
    if puntaje >= config.CONFIANZA_MEDIA:
        return "media"
    return "baja"


def _fuente(n: NodeWithScore) -> dict:
    """Cita de un fragmento: herramienta, actividad o sección (la más específica) y página."""
    m = n.node.metadata
    return {
        "seccion": m.get("herramienta") or m.get("actividad") or m.get("seccion"),
        "pagina": m["pagina_inicio"],
        "fuente": m["fuente"],  # «Sección › Herramienta, p. N», como lo cita el LLM
        "fragmento": n.node.get_content()[:300],
        "puntaje": round(float(n.score), 3),
    }


def _contexto(nodos: list[NodeWithScore]) -> str:
    """Fragmentos para el prompt; cada uno empieza con su línea «fuente:»."""
    return "\n\n---\n\n".join(n.node.get_content(metadata_mode=MetadataMode.LLM) for n in nodos)


def _generar(pregunta: str, etapa: int | None, nodos: list[NodeWithScore]) -> str:
    """Llama al LLM con el prompt y los fragmentos. RuntimeError si Ollama no responde."""
    mensajes = [
        ChatMessage(role=MessageRole.SYSTEM, content=SISTEMA),
        ChatMessage(role=MessageRole.USER, content=USUARIO.format(
            etapa=texto_etapa(etapa), contexto=_contexto(nodos), pregunta=pregunta)),
    ]
    try:
        return (llm().chat(mensajes).message.content or "").strip()
    except ConnectionError as e:
        raise RuntimeError(f"El modelo local no está disponible en {config.OLLAMA_URL}. "
                           "Inicia Ollama (ollama serve).") from e
    except httpx.TimeoutException as e:
        raise RuntimeError(f"El modelo local no respondió en {config.TIMEOUT_S:.0f} s.") from e
    except ResponseError as e:
        if e.status_code == 404:
            raise RuntimeError(f"Ollama no tiene el modelo «{config.LLM}». "
                               f"Descárgalo con: ollama pull {config.LLM}") from e
        raise RuntimeError(f"Error del modelo local: {e.error}") from e


def responder(pregunta: str, etapa: int | None = None, filtrar_etapa: bool = False) -> Respuesta:
    """
    Responde `pregunta` usando solo la guía.

    `etapa` (1 a 7) se le indica al LLM para resolver preguntas ambiguas; con
    `filtrar_etapa=True`, además, solo se buscan fragmentos de esa etapa.
    Lanza RuntimeError si el LLM local no está disponible.
    """
    t0 = time.time()
    # El umbral está calibrado sobre el puntaje del reranker, así que siempre se usa.
    nodos = recuperar(pregunta, etapa if filtrar_etapa else None, usar_reranker=True)
    mejor = round(float(nodos[0].score), 3) if nodos else None
    nodos = SimilarityPostprocessor(similarity_cutoff=config.UMBRAL).postprocess_nodes(
        nodos, query_bundle=QueryBundle(pregunta))

    if not nodos:  # ningún fragmento es relevante: no se llama al LLM
        return Respuesta(resultado=f"{MENSAJE_NO_ENCONTRADA} {SUGERENCIA}", encontrada=False, confianza=None,
                         puntaje=mejor, latencia_s=round(time.time() - t0, 1))

    texto = _generar(pregunta, etapa, nodos)
    encontrada = not texto.startswith(MENSAJE_NO_ENCONTRADA)
    return Respuesta(
        resultado=texto,
        encontrada=encontrada,
        confianza=confianza(mejor) if encontrada else None,
        fuentes=[_fuente(n) for n in nodos] if encontrada else [],
        puntaje=mejor,
        latencia_s=round(time.time() - t0, 1),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta")
    ap.add_argument("--etapa", type=int, help="etapa del proyecto (1-7), se le indica al LLM")
    ap.add_argument("--filtrar-etapa", action="store_true", help="busca solo fragmentos de esa etapa")
    ap.add_argument("--json", action="store_true", help="salida con la forma del contrato")
    args = ap.parse_args()

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
