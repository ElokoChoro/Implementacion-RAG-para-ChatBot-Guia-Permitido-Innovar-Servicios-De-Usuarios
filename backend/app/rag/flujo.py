"""
Pasos comunes de las respuestas con la guía: los usan generar.py (preguntas) y
sugerir.py (próximos pasos de una etapa).

  sobre_el_umbral   deja los fragmentos con puntaje del reranker ≥ UMBRAL y
                    devuelve también el mejor puntaje, para informarlo aunque
                    ninguno pase
  contexto          los fragmentos como los lee el LLM: cada uno con su línea «fuente:»
  chat              llama al LLM; si el servidor falla, RuntimeError con qué hacer
  armar_respuesta   la `Respuesta` del contrato: rechazo, confianza y fuentes

Lo que cambia entre los dos (los mensajes, el texto cuando ningún fragmento
pasa el umbral, la corrección de citas) queda en cada módulo. Así un cambio del
umbral, de la detección del rechazo o de la forma de las fuentes llega a las dos
rutas de la API.

La confianza sale del mejor puntaje del reranker (CONFIANZA_MEDIA, CONFIANZA_ALTA)
y las fuentes de los metadatos de los fragmentos, nunca del texto del LLM. El
rechazo se detecta buscando MENSAJE_NO_ENCONTRADA al inicio de la respuesta: si
cambia esa frase o la regla del caso C de prompts.py, revisa armar_respuesta.
"""
from __future__ import annotations

import time

import httpx
import openai
from llama_index.core.llms import ChatMessage
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle
from ollama import ResponseError

from app.rag import config
from app.rag.contrato import Fuente, Respuesta
from app.rag.modelos import llm
from app.rag.prompts import MENSAJE_NO_ENCONTRADA


def sobre_el_umbral(nodos: list[NodeWithScore], consulta: str) -> tuple[list[NodeWithScore], float | None]:
    """
    Fragmentos con puntaje ≥ UMBRAL y el mejor puntaje de todos (None si no hay ninguno).

    El umbral está calibrado sobre el puntaje del reranker: `nodos` tiene que
    venir de recuperar() con el reranker.
    """
    mejor = round(float(nodos[0].score), 3) if nodos else None
    relevantes = SimilarityPostprocessor(similarity_cutoff=config.UMBRAL).postprocess_nodes(
        nodos, query_bundle=QueryBundle(consulta))
    return relevantes, mejor


def confianza(puntaje: float) -> str:
    """Nivel de confianza según el mejor puntaje del reranker."""
    if puntaje >= config.CONFIANZA_ALTA:
        return "alta"
    if puntaje >= config.CONFIANZA_MEDIA:
        return "media"
    return "baja"


def fuente(n: NodeWithScore) -> Fuente:
    """Cita de un fragmento: herramienta, actividad o sección (la más específica) y página."""
    m = n.node.metadata
    return {
        "seccion": m.get("herramienta") or m.get("actividad") or m["seccion"],
        "pagina": m["pagina_inicio"],
        "fuente": m["fuente"],  # «Sección › Herramienta, p. N», como lo cita el LLM
        "fragmento": n.node.get_content()[:300],
        "puntaje": round(float(n.score), 3),
    }


def contexto(nodos: list[NodeWithScore]) -> str:
    """Fragmentos para el prompt; cada uno empieza con su línea «fuente:»."""
    return "\n\n---\n\n".join(n.node.get_content(metadata_mode=MetadataMode.LLM) for n in nodos)


def chat(mensajes: list[ChatMessage]) -> str:
    """
    Respuesta del LLM a `mensajes`. RuntimeError con qué hacer si el servidor del LLM falla.

    El cliente se crea en modelos.llm(); un proveedor nuevo agrega aquí sus errores.
    """
    try:
        return (llm().chat(mensajes).message.content or "").strip()
    # APITimeoutError hereda de APIConnectionError: va antes.
    except (httpx.TimeoutException, openai.APITimeoutError) as e:
        raise RuntimeError(f"El modelo no respondió en {config.TIMEOUT_S:.0f} s. "
                           "Sube TIMEOUT_S o usa un modelo más chico.") from e
    except (ConnectionError, openai.APIConnectionError) as e:
        como = ("Inicia Ollama (ollama serve)." if config.PROVEEDOR_LLM == "ollama"
                else "Inicia el servidor del modelo y revisa LLM_URL en .env.")
        raise RuntimeError(f"El modelo no está disponible en {config.url_llm()}. {como}") from e
    except ResponseError as e:
        if e.status_code == 404:
            raise RuntimeError(f"Ollama no tiene el modelo «{config.LLM}». "
                               f"Descárgalo con: ollama pull {config.LLM}") from e
        raise RuntimeError(f"Error del modelo: {e.error}") from e
    except openai.NotFoundError as e:
        raise RuntimeError(f"El servidor en {config.LLM_URL} no tiene el modelo «{config.LLM}». "
                           f"Revisa el nombre en {config.LLM_URL}/models y ponlo en LLM.") from e
    except openai.AuthenticationError as e:
        raise RuntimeError(f"El servidor en {config.LLM_URL} rechazó la clave. Guárdala con: "
                           "python -m app.rag.secretos guardar LLM_API_KEY") from e
    except openai.APIStatusError as e:
        raise RuntimeError(f"Error del modelo: {e.message}") from e


def armar_respuesta(texto: str, nodos: list[NodeWithScore], mejor: float | None, inicio: float,
                    **campos) -> Respuesta:
    """
    `Respuesta` con `texto`, del LLM o fijo cuando ningún fragmento pasó el umbral.

    Si `texto` empieza con MENSAJE_NO_ENCONTRADA, la guía no responde: sin
    confianza ni fuentes. Si no, la confianza sale de `mejor` y las fuentes de
    `nodos`. `inicio` es la hora (time.time()) en que empezó la consulta; `campos`
    va tal cual a Respuesta (por ejemplo, `version_prompt`).
    """
    encontrada = not texto.startswith(MENSAJE_NO_ENCONTRADA)
    return Respuesta(
        resultado=texto,
        encontrada=encontrada,
        confianza=confianza(mejor) if encontrada and mejor is not None else None,
        fuentes=[fuente(n) for n in nodos] if encontrada else [],
        puntaje=mejor,
        latencia_s=round(time.time() - inicio, 1),
        **campos,
    )
