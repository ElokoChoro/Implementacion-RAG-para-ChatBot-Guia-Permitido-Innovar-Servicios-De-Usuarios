"""
API HTTP del módulo RAG, para la interfaz de chat de demo y la plataforma SSP-UXLab.

    POST /ia/consultar-guia          {"pregunta": "...", "etapa": 7, "filtrar_etapa": false}
                                     → la `Respuesta` de contrato.py (resultado, encontrada,
                                       confianza, fuentes…)
    POST /ia/sugerir-proximos-pasos  {"etapa": 7, "contexto": "...", "datos_etapa": {...}}
                                     → la misma `Respuesta`, con los próximos pasos de la
                                       etapa (sugerir.py)
    GET  /salud                      configuración con la que corre, sin cargar modelos

Las preguntas se atienden de a una: bge-m3, el reranker y el LLM comparten la
memoria del equipo y dos consultas a la vez no caben en un Mac de 8 GB. Los
modelos se cargan con la primera pregunta, que por eso tarda más.

Con MODO=simulador responde simulador.py en vez de generar.py y sugerir.py: mismas rutas,
validación, errores y forma de respuesta, pero con respuestas fijas y sin
importar LlamaIndex ni los modelos. Sirve para que la plataforma integre la API
sin el equipo que tiene los modelos; las marcas para probar cada caso están en
simulador.py.

Si CLAVE_SERVICIO tiene valor, los dos POST exigen
«Authorization: Bearer <clave>» y responde 401 sin ella. La API la llama el
backend de la plataforma, no el navegador: la clave nunca va en el frontend.
/salud no pide clave, para que el servidor pueda revisar que la API está viva.

Desde backend/ (el servidor del LLM corriendo con el modelo de config.LLM):
    ../.venv/bin/uvicorn app.api:app --port 8000
Simulador, solo con backend/requirements-simulador.txt instalado:
    MODO=simulador uvicorn app.api:app --port 8000
"""
from __future__ import annotations

import secrets
import threading
from functools import cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.rag import config
from app.rag.contrato import Respuesta

if config.MODO == "simulador":
    from app.rag.simulador import responder, sugerir
else:
    from app.rag.generar import responder
    from app.rag.sugerir import sugerir

app = FastAPI(title="RAG · Permitido Innovar")
_turno = threading.Lock()
_bearer = HTTPBearer(auto_error=False, description="CLAVE_SERVICIO. Si el servidor no tiene una, no se pide.")


class Consulta(BaseModel):
    pregunta: str = Field(min_length=1, max_length=1000, examples=["¿Qué es un plano del servicio?"])
    etapa: int | None = Field(default=None, ge=1, le=7, description="etapa del proyecto, se le indica al LLM")
    filtrar_etapa: bool = Field(default=False, description="busca solo fragmentos de esa etapa")


class SolicitudEtapa(BaseModel):
    # Los mismos campos que ya envía la plataforma a su /ia/sugerir-proximos-pasos.
    etapa: int = Field(ge=1, le=7, description="etapa del Propósito 1 en que está el proyecto")
    contexto: str | dict[str, Any] | None = Field(
        default=None, description="lo que el equipo registró del proyecto, en texto o como diccionario",
        examples=["Renovación del permiso de circulación"])
    datos_etapa: dict[str, Any] | None = Field(
        default=None, description="avance registrado en la etapa", examples=[{"mapa_momentos_criticos": "pendiente"}])


@cache
def _clave_servicio() -> str:
    # Se lee una vez: consultar el llavero en cada pregunta es lento.
    return config.clave_servicio()


def _verificar_clave(credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> None:
    clave = _clave_servicio()
    if not clave:
        return
    # compare_digest: compara en tiempo constante, para no dar pistas de la clave.
    if credenciales is None or not secrets.compare_digest(credenciales.credentials.encode(), clave.encode()):
        raise HTTPException(status_code=401, detail="Falta la clave de servicio o no es válida.",
                            headers={"WWW-Authenticate": "Bearer"})


@app.post("/ia/consultar-guia", response_model=Respuesta, dependencies=[Depends(_verificar_clave)])
def consultar_guia(consulta: Consulta) -> dict:
    # `def` y no `async def`: FastAPI la corre en un hilo aparte y el servidor sigue
    # respondiendo /salud mientras se genera la respuesta.
    pregunta = consulta.pregunta.strip()
    if not pregunta:
        raise HTTPException(status_code=422, detail="La pregunta está vacía.")
    with _turno:
        try:
            return responder(pregunta, consulta.etapa, consulta.filtrar_etapa).a_dict()
        except RuntimeError as e:  # servidor del LLM caído, sin el modelo o sin responder
            raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/ia/sugerir-proximos-pasos", response_model=Respuesta, dependencies=[Depends(_verificar_clave)])
def sugerir_proximos_pasos(solicitud: SolicitudEtapa) -> dict:
    # No hace falta un tope para `contexto` y `datos_etapa`: sugerir.texto_proyecto los
    # corta en MAX_CARACTERES_PROYECTO antes de que lleguen al LLM.
    with _turno:
        try:
            return sugerir(solicitud.etapa, solicitud.contexto, solicitud.datos_etapa).a_dict()
        except RuntimeError as e:  # servidor del LLM caído, sin el modelo o sin responder
            raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/salud")
def salud() -> dict:
    return {"modo": config.MODO, "almacen": config.ALMACEN, "proveedor_llm": config.PROVEEDOR_LLM,
            "llm_url": config.url_llm(), "llm": config.LLM, "embeddings": config.EMBEDDINGS,
            "reranker": config.RERANKER, "umbral": config.UMBRAL}
