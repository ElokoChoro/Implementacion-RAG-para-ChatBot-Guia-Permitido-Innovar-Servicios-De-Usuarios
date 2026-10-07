"""
API HTTP del módulo RAG, para la interfaz de chat de demo y la plataforma SSP-UXLab.

    POST /ia/consultar-guia          {"pregunta": "...", "etapa": 7, "filtrar_etapa": false}
                                     → la `Respuesta` de contrato.py (resultado, encontrada,
                                       confianza, fuentes…)
    POST /ia/sugerir-proximos-pasos  {"etapa": 7, "contexto": "...", "datos_etapa": {...}}
                                     → la misma `Respuesta`, con los próximos pasos de la
                                       etapa (sugerir.py)
    POST /ia/adjuntos                multipart con el campo «archivo» (PDF o DOCX; ver
                                     FORMATOS_ADJUNTO) → `AdjuntoCargado` (app/adjuntos/):
                                     el archivo leído, seudonimizado e indexado en memoria
    DELETE /ia/adjuntos/{id}         quita el adjunto de la memoria (204, o 404 si no está)
    GET  /salud                      configuración con la que corre y si los modelos ya
                                     están cargados (`listo`), sin cargarlos

Las preguntas se atienden de a una: bge-m3, el reranker y el LLM comparten la
memoria del equipo y dos consultas a la vez no caben en un Mac de 8 GB. Los
adjuntos esperan el mismo turno, porque usan bge-m3 y Docling; antes de pedirlo
se valida el archivo, para que uno inválido no haga cola. Mientras
se atiende una, esperan turno hasta COLA_MAXIMA más, cada una ESPERA_TURNO_S
como máximo; las que no caben o no alcanzan turno reciben 503 con Retry-After,
para que quien llama reintente más tarde. /salud no espera turno.

Los modelos se cargan con la primera pregunta, que por eso tarda más. Con
PRECARGAR=true se cargan al arrancar, en segundo plano: /salud responde desde el
inicio y `listo` pasa a true cuando terminan. El LLM no se precarga: corre en su
propio servidor (Ollama u otro), que lo carga con la primera consulta.

Con MODO=simulador responde simulador.py en vez de generar.py y sugerir.py: mismas rutas,
validación, errores y forma de respuesta, pero con respuestas fijas y sin
importar LlamaIndex ni los modelos. Sirve para que la plataforma integre la API
sin el equipo que tiene los modelos; las marcas para probar cada caso están en
simulador.py.

Si CLAVE_SERVICIO tiene valor, los POST y el DELETE exigen
«Authorization: Bearer <clave>» y responde 401 sin ella. La API la llama el
backend de la plataforma, no el navegador: la clave nunca va en el frontend.
/salud no pide clave, para que el servidor pueda revisar que la API está viva.
Si CLAVE_SERVICIO está vacía, la API lo avisa en el log al arrancar.

Los errores esperables (servidor del LLM o índice de Supabase no disponibles)
responden 503 con qué revisar en `detail`; cualquier otro, 500 con un `detail`
genérico, y la traza queda en el log de uvicorn.

Desde backend/ (el servidor del LLM corriendo con el modelo de config.LLM):
    ../.venv/bin/uvicorn app.api:app --port 8000
Simulador, solo con backend/requirements-simulador.txt instalado:
    MODO=simulador uvicorn app.api:app --port 8000
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.adjuntos.extraer import validar
from app.adjuntos.tipos import NO_DISPONIBLE, AdjuntoCargado, ErrorAdjunto
from app.rag import config, registro
from app.rag.contrato import Respuesta

if config.MODO == "simulador":
    from app.rag.simulador import adjuntos_vigentes, borrar_adjunto, cargar_adjunto, responder, sugerir
else:
    from app.adjuntos.cargar import cargar_adjunto
    from app.adjuntos.indice import borrar as borrar_adjunto, vigentes as adjuntos_vigentes
    from app.rag.generar import responder
    from app.rag.sugerir import sugerir

registro.configurar()
log = logging.getLogger("app.api")

# Turno: una consulta a la vez. Cupos: la que se atiende más las que pueden esperar.
_turno = threading.Lock()
_cupos = threading.BoundedSemaphore(1 + config.COLA_MAXIMA)
# Se marca cuando los modelos están cargados: al terminar la precarga o la primera consulta.
_listo = threading.Event()
# Segundos que se sugiere esperar antes de reintentar, del orden de una respuesta (las
# medidas tardaron entre 89 y 298 s en un Mac M2 de 8 GB).
REINTENTAR_S = 120

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


def _precargar() -> None:
    """Carga los modelos en segundo plano, con el turno tomado: una consulta no los carga dos veces."""
    from app.rag.recuperar import precargar

    t0 = time.time()
    with _turno:
        try:
            precargar()
        except Exception:
            log.exception("No se pudieron precargar los modelos; se cargarán con la primera consulta.")
            return
    _listo.set()
    log.info("Modelos precargados en %.0f s.", time.time() - t0)


@asynccontextmanager
async def _ciclo(_app: FastAPI) -> AsyncIterator[None]:
    """Al arrancar: avisa si la API no pide clave y, con PRECARGAR, carga los modelos."""
    if not _clave_servicio():
        log.warning("CLAVE_SERVICIO está vacía: la API no pide clave. Defínela si otra máquina "
                    "puede llegar a este puerto.")
    if config.MODO == "simulador":
        _listo.set()  # no hay modelos que cargar
    elif config.PRECARGAR:
        threading.Thread(target=_precargar, name="precarga", daemon=True).start()
    yield


app = FastAPI(title="RAG · Permitido Innovar", lifespan=_ciclo)


@app.exception_handler(Exception)
async def _error_inesperado(_request: Request, _error: Exception) -> JSONResponse:
    # Un error que no es del LLM ni del índice es un bug: la traza la registra uvicorn y
    # quien llama recibe JSON con `detail`, como en los demás errores.
    return JSONResponse(status_code=500, content={"detail": "Error inesperado del servidor. "
                                                            "El detalle quedó en su log."})


def _ocupada() -> HTTPException:
    return HTTPException(status_code=503, headers={"Retry-After": str(REINTENTAR_S)},
                         detail="La API está atendiendo otras consultas. Reintenta en unos minutos.")


def _con_turno[T](ruta: str, tarea: Callable[[], T]) -> tuple[T, float]:
    """
    Corre `tarea` cuando le toca el turno y devuelve su resultado y los segundos que esperó.

    503 si la cola está llena, si no llega el turno en ESPERA_TURNO_S o si la
    tarea lanza RuntimeError (servidor del LLM o índice no disponibles). Cualquier
    otra excepción sale tal cual, con el turno ya devuelto.
    """
    t0 = time.time()
    if not _cupos.acquire(blocking=False):
        log.warning(registro.campos(ruta=ruta, estado=503, motivo="cola_llena"))
        raise _ocupada()
    try:
        if not _turno.acquire(timeout=config.ESPERA_TURNO_S):
            log.warning(registro.campos(ruta=ruta, estado=503, motivo="sin_turno",
                                        espera_s=round(time.time() - t0, 1)))
            raise _ocupada()
        espera = round(time.time() - t0, 1)
        try:
            return tarea(), espera
        except RuntimeError as e:
            log.error(registro.campos(ruta=ruta, estado=503, motivo=str(e), espera_s=espera))
            raise HTTPException(status_code=503, detail=str(e)) from e
        finally:
            _turno.release()
    finally:
        _cupos.release()


def _atender(ruta: str, consulta: Callable[[], Respuesta]) -> dict:
    """Corre `consulta` con turno (ver _con_turno) y deja una línea en el log con el resultado."""
    respuesta, espera = _con_turno(ruta, consulta)
    _listo.set()
    log.info(registro.campos(ruta=ruta, estado=200, espera_s=espera, latencia_s=respuesta.latencia_s,
                             encontrada=respuesta.encontrada, confianza=respuesta.confianza,
                             mejor=respuesta.puntaje, fuentes=len(respuesta.fuentes), modo=respuesta.modo,
                             prompt=respuesta.version_prompt))
    return respuesta.a_dict()


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
    # `def` y no `async def`: FastAPI la corre en un hilo aparte mientras espera turno y
    # se genera la respuesta, sin bloquear al servidor.
    pregunta = consulta.pregunta.strip()
    if not pregunta:
        raise HTTPException(status_code=422, detail="La pregunta está vacía.")
    return _atender("consultar-guia", lambda: responder(pregunta, consulta.etapa, consulta.filtrar_etapa))


@app.post("/ia/sugerir-proximos-pasos", response_model=Respuesta, dependencies=[Depends(_verificar_clave)])
def sugerir_proximos_pasos(solicitud: SolicitudEtapa) -> dict:
    # No hace falta un tope para `contexto` y `datos_etapa`: sugerir.texto_proyecto los
    # corta en MAX_CARACTERES_PROYECTO antes de que lleguen al LLM.
    return _atender("sugerir-proximos-pasos",
                    lambda: sugerir(solicitud.etapa, solicitud.contexto, solicitud.datos_etapa))


def _rechazar_adjunto(e: ErrorAdjunto, kb: int, **campos) -> HTTPException:
    # El motivo va a la persona; al log solo el código, sin el nombre del archivo ni su texto.
    log.info(registro.campos(ruta="adjuntos", estado=e.estado, kb=kb, **campos))
    return HTTPException(status_code=e.estado, detail=e.mensaje)


@app.post("/ia/adjuntos", response_model=AdjuntoCargado, dependencies=[Depends(_verificar_clave)])
def subir_adjunto(archivo: Annotated[UploadFile, File(description="PDF o DOCX (ver FORMATOS_ADJUNTO en /salud)")]
                  ) -> dict:
    # Se lee un byte más que el tope: alcanza para rechazar un archivo grande sin leerlo entero.
    datos = archivo.file.read(int(config.MAX_MB_ADJUNTO * 1024 * 1024) + 1)
    nombre = archivo.filename or ""
    kb = round(len(datos) / 1024)
    try:
        formato = validar(nombre, datos)
    except ErrorAdjunto as e:
        raise _rechazar_adjunto(e, kb) from e
    try:
        adjunto, espera = _con_turno("adjuntos", lambda: cargar_adjunto(nombre, datos))
    except ErrorAdjunto as e:
        raise _rechazar_adjunto(e, kb, formato=formato) from e
    log.info(registro.campos(ruta="adjuntos", estado=200, formato=formato, kb=kb, paginas=adjunto.paginas,
                             fragmentos=adjunto.fragmentos, reemplazos=sum(adjunto.reemplazos.values()),
                             espera_s=espera, latencia_s=adjunto.latencia_s, modo=adjunto.modo))
    return adjunto.a_dict()


@app.delete("/ia/adjuntos/{adjunto_id}", status_code=204, dependencies=[Depends(_verificar_clave)])
def quitar_adjunto(adjunto_id: str) -> Response:
    # Sin turno: solo saca el adjunto de la memoria.
    if not borrar_adjunto(adjunto_id):
        raise HTTPException(status_code=404, detail=NO_DISPONIBLE)
    return Response(status_code=204)


@app.get("/salud")
async def salud() -> dict:
    # `async def`: corre en el bucle del servidor y no en el grupo de hilos, que pueden
    # estar ocupados por consultas que esperan turno.
    return {"modo": config.MODO, "listo": _listo.is_set(), "clave": bool(_clave_servicio()),
            "almacen": config.ALMACEN, "proveedor_llm": config.PROVEEDOR_LLM,
            "llm_url": config.url_llm(), "llm": config.LLM, "embeddings": config.EMBEDDINGS,
            "reranker": config.RERANKER, "umbral": config.UMBRAL,
            "formatos_adjunto": list(config.FORMATOS_ADJUNTO), "max_mb_adjunto": config.MAX_MB_ADJUNTO,
            "adjuntos_vigentes": adjuntos_vigentes()}
