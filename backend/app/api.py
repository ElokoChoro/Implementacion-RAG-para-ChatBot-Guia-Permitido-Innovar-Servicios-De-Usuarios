"""
API HTTP del módulo RAG, para la interfaz de chat de demo.

    POST /ia/consultar-guia   {"pregunta": "...", "etapa": 7, "filtrar_etapa": false}
                              → la `Respuesta` de generar.py (resultado, encontrada,
                                confianza, fuentes…)
    GET  /salud               configuración con la que corre, sin cargar modelos

Las preguntas se atienden de a una: bge-m3, el reranker y el LLM comparten la
memoria del equipo y dos consultas a la vez no caben en un Mac de 8 GB. Los
modelos se cargan con la primera pregunta, que por eso tarda más.

Desde backend/ (Ollama corriendo con el modelo de config.LLM):
    ../.venv/bin/uvicorn app.api:app --port 8000
"""
from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.rag import config
from app.rag.generar import responder

app = FastAPI(title="RAG · Permitido Innovar")
_turno = threading.Lock()


class Consulta(BaseModel):
    pregunta: str = Field(min_length=1, max_length=1000)
    etapa: int | None = Field(default=None, ge=1, le=7, description="etapa del proyecto, se le indica al LLM")
    filtrar_etapa: bool = Field(default=False, description="busca solo fragmentos de esa etapa")


@app.post("/ia/consultar-guia")
def consultar_guia(consulta: Consulta) -> dict:
    # `def` y no `async def`: FastAPI la corre en un hilo aparte y el servidor sigue
    # respondiendo /salud mientras se genera la respuesta.
    pregunta = consulta.pregunta.strip()
    if not pregunta:
        raise HTTPException(status_code=422, detail="La pregunta está vacía.")
    with _turno:
        try:
            return responder(pregunta, consulta.etapa, consulta.filtrar_etapa).a_dict()
        except RuntimeError as e:  # Ollama caído, sin el modelo o sin responder
            raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/salud")
def salud() -> dict:
    return {"almacen": config.ALMACEN, "llm": config.LLM, "embeddings": config.EMBEDDINGS,
            "reranker": config.RERANKER, "umbral": config.UMBRAL}
