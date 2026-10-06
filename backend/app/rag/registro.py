"""
Registro (logging) del backend: una línea «clave=valor» por evento.

    app.api            una por solicitud: ruta, estado, espera de turno, latencia y resultado,
                       o el motivo del 503
    app.rag.generar    tiempos de una pregunta (recuperación y LLM), fragmentos, mejor puntaje
                       y tokens del LLM (tokens_prompt, tokens_respuesta)
    app.rag.sugerir    lo mismo para los próximos pasos de una etapa

No se registra el texto de la pregunta ni lo que el equipo escribió de su proyecto:
pueden traer datos personales de quienes atiende la institución. Se registra su
largo, que alcanza para ver si las preguntas muy cortas se rechazan más.

Sirve para operar la API (cuántas consultas esperan turno o reciben 503, cuánto
tarda el LLM frente a la recuperación) y para revisar el UMBRAL con preguntas
reales: `mejor` es el puntaje del reranker de cada una, también de las rechazadas.

Los tokens son los que informa el servidor del LLM (flujo.tokens). Con un modelo
local no tienen costo por uso, pero miden cuánto trabaja el LLM; con un servicio
que cobra por token, su suma da el costo. Una consulta que el umbral rechaza
registra 0, porque no llama al LLM; «-» quiere decir que el servidor no los informó.

Con uvicorn, las líneas salen junto a su log. Desde la terminal, desde backend/:
    python -m app.rag.generar "¿Qué es un plano del servicio?"   # la línea de tiempos sale primero
"""
from __future__ import annotations

import logging


def configurar(nivel: int = logging.INFO) -> None:
    """
    Muestra los logs de app.* en stderr, con fecha y hora.

    Sin esto, Python solo muestra WARNING y sin formato. Solo se configura el
    logger «app», no el raíz: así no aparecen los logs de httpx o de FlagEmbedding.
    """
    raiz = logging.getLogger("app")
    if raiz.handlers:
        return
    manejador = logging.StreamHandler()
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                                             "%Y-%m-%d %H:%M:%S"))
    raiz.addHandler(manejador)
    raiz.setLevel(nivel)


def _valor(v: object) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".")
    texto = str(v)
    return f'"{texto}"' if " " in texto else texto


def campos(**valores: object) -> str:
    """«clave=valor» separados por espacios, fáciles de filtrar con grep. None se muestra como «-»."""
    return " ".join(f"{clave}={_valor(v)}" for clave, v in valores.items())
