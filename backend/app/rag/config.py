"""
Configuración del módulo RAG.

Cada valor se puede cambiar con una variable de entorno del mismo nombre, sin
tocar el código. Por ejemplo, para recuperar 6 fragmentos a partir de 30
candidatos:

    TOP_K=6 RERANKER_CANDIDATOS=30 python -m app.rag.recuperar "¿Qué es un plano del servicio?"

Variables disponibles
---------------------
VERSION_CORPUS         Versión del corpus en data/corpus/ (por defecto «v3»).
EMBEDDINGS             Modelo de embeddings de Hugging Face («BAAI/bge-m3»).
RERANKER               Modelo reranker de Hugging Face («BAAI/bge-reranker-v2-m3»).
DISPOSITIVO            «cpu», «mps» (Apple Silicon) o «cuda:0». Vacío: lo elige FlagEmbedding.
FP16                   Usa media precisión (true/false). Ahorra la mitad de memoria.
MAX_TOKENS_EMBEDDING   Largo máximo, en tokens del modelo, de cada texto que se vectoriza.
MAX_TOKENS_RERANKER    Largo máximo del par (pregunta, fragmento) que lee el reranker.
CHUNK_TOKENS           Tamaño máximo de cada fragmento, en tokens.
CHUNK_OVERLAP          Tokens que comparten dos fragmentos seguidos.
RERANKER_CANDIDATOS    Fragmentos que se recuperan por similitud antes del reranker.
TOP_K                  Fragmentos que se entregan al final.
USAR_RERANKER          Si es false, se entregan los TOP_K más similares sin reordenar.
ALMACEN                Vector store: «chroma» (local, por defecto) o «pgvector» (Supabase).
RUTA_CHROMA            Carpeta donde Chroma guarda el índice.
SUPABASE_DB_URL        Connection string de Postgres de Supabase (solo con ALMACEN=pgvector).
                       Es una credencial: va en el llavero del sistema o, en equipos sin
                       llavero, en .env (python -m app.rag.secretos guardar elige; ver secretos.py).
TABLA_PGVECTOR         Tabla del índice en pgvector, sin el prefijo «data_» de PGVectorStore.
PROVEEDOR_LLM          «ollama» (por defecto) u «openai»: cualquier servidor compatible con
                       la API de OpenAI, como LM Studio o llama.cpp.
OLLAMA_URL             Dirección del servidor de Ollama (con PROVEEDOR_LLM=ollama).
LLM_URL                URL base del servidor compatible con OpenAI (con PROVEEDOR_LLM=openai).
LLM_API_KEY            Clave de ese servidor; los locales no la piden. Si es un servicio en la
                       nube, es una credencial: se guarda como SUPABASE_DB_URL.
LLM                    Modelo que redacta la respuesta («gemma3:4b»), con el nombre que
                       le da el servidor.
TEMPERATURE            Aleatoriedad del LLM; baja para que se apegue a la guía.
CONTEXTO_TOKENS        Ventana de contexto del LLM (num_ctx de Ollama; en otros servidores
                       se fija al cargar el modelo y este valor debe coincidir).
MAX_TOKENS_RESPUESTA   Largo máximo de la respuesta, en tokens.
TIMEOUT_S              Segundos de espera al LLM antes de dar error.
MAX_CARACTERES_PROYECTO  Largo máximo del contexto del proyecto que recibe el asistente por etapa.
UMBRAL                 Puntaje mínimo del reranker (0 a 1) para que un fragmento llegue al LLM.
CONFIANZA_MEDIA        Mejor puntaje desde el que la confianza es «media».
CONFIANZA_ALTA         Mejor puntaje desde el que la confianza es «alta».
MODO                   «local» (por defecto): responde con los modelos. «simulador»: respuestas
                       fijas con la forma del contrato, sin modelos (ver simulador.py).
SIMULADOR_DEMORA_S     Segundos que espera el simulador antes de responder (0 por defecto).
CLAVE_SERVICIO         Clave que la API exige como «Authorization: Bearer <clave>». Vacía: la API
                       no pide clave (uso local). Es una credencial: se guarda como
                       SUPABASE_DB_URL; en un servidor, como variable de entorno.
COLA_MAXIMA            Consultas que pueden esperar turno mientras se atiende una; con más, la API
                       responde 503 de inmediato.
ESPERA_TURNO_S         Segundos que una consulta espera turno antes de responder 503.
PRECARGAR              Si es true, la API carga bge-m3, el reranker y el índice al arrancar, en
                       segundo plano, en vez de con la primera consulta.
FORMATOS_ADJUNTO       Formatos de adjunto que acepta POST /ia/adjuntos, separados por coma
                       («pdf,docx»). El código también lee «md».
MAX_MB_ADJUNTO         Tamaño máximo de un adjunto, en MB.
MAX_PAGINAS_ADJUNTO    Páginas máximas de un PDF adjunto.
MIN_CARACTERES_PAGINA  Caracteres por página, en promedio, bajo los que un PDF se trata como escaneado.
MINUTOS_ADJUNTO        Minutos que un adjunto queda en memoria desde que se subió.
MAX_ADJUNTOS           Adjuntos en memoria a la vez; al subir uno más se descarta el más antiguo.
MAX_CARACTERES_ENTREGABLE  Largo máximo de un entregable que la revisión le pasa entero al LLM; uno
                       más largo se revisa con los fragmentos más relevantes para cada punto.

Si cambian EMBEDDINGS, CHUNK_TOKENS, CHUNK_OVERLAP o VERSION_CORPUS, hay que
volver a indexar (python -m ingesta.indexar). En Chroma cada combinación usa su
propia colección (ver `coleccion()`), así que los índices anteriores no se pisan.
En pgvector hay una sola tabla, que se recarga completa al indexar.

Las variables también se leen del archivo .env de la raíz del repositorio (ver
.env.example); las que ya están definidas en el entorno tienen prioridad. Las
credenciales van en el llavero del sistema si el equipo tiene uno, y si no en
.env (ver secretos.py).
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.adjuntos.tipos import FORMATOS  # los que sabe leer app/adjuntos/extraer.py
from app.rag import secretos

RAIZ = Path(__file__).resolve().parents[3]  # raíz del repositorio
load_dotenv(RAIZ / ".env")


def _env(nombre: str, defecto: Any, tipo: Callable[[str], Any] = str) -> Any:
    """Lee una variable de entorno y la convierte a `tipo`; si falta o está vacía, usa `defecto`."""
    valor = os.getenv(nombre)
    if valor in (None, ""):
        return defecto
    if tipo is bool:
        return valor.strip().lower() in ("1", "true", "si", "sí")
    return tipo(valor)


def _env_opcion(nombre: str, defecto: str, opciones: tuple[str, ...]) -> str:
    """
    Lee una variable que solo admite `opciones`. ValueError al importar si trae otra:
    así un «MODO=simuladr» falla al arrancar y no carga los modelos sin avisar.
    """
    valor = _env(nombre, defecto).strip().lower()
    if valor not in opciones:
        raise ValueError(f"{nombre}={valor!r} no es válido. Usa uno de: {', '.join(opciones)}.")
    return valor


# ---- Corpus -------------------------------------------------------------------
# El corpus es el texto de la guía ya extraído y dividido en páginas con sus
# metadatos. Se versiona en el repositorio; el PDF original no.
VERSION_CORPUS = _env("VERSION_CORPUS", "v3")
RUTA_PAGINAS = RAIZ / "data" / "corpus" / VERSION_CORPUS / "paginas.jsonl"

# ---- Modelos locales (FlagEmbedding) -----------------------------------------
# Ambos se descargan de Hugging Face la primera vez y después corren sin red.
EMBEDDINGS = _env("EMBEDDINGS", "BAAI/bge-m3")
# Dimensión de los vectores de bge-m3. Define el tamaño de la columna si el
# índice se guarda en pgvector; cambiar de modelo obliga a recrearla.
EMBEDDINGS_DIM = 1024
RERANKER = _env("RERANKER", "BAAI/bge-reranker-v2-m3")
DISPOSITIVO = _env("DISPOSITIVO", "")
# En CPU, FlagEmbedding ignora FP16 y usa precisión completa.
FP16 = _env("FP16", True, bool)
# Se cuentan con el tokenizador de los modelos BGE (XLM-RoBERTa). Un fragmento
# de 400 tokens (contados con tiktoken) más la pregunta cabe de sobra en 1024.
MAX_TOKENS_EMBEDDING = _env("MAX_TOKENS_EMBEDDING", 1024, int)
MAX_TOKENS_RERANKER = _env("MAX_TOKENS_RERANKER", 1024, int)

# ---- Fragmentación ------------------------------------------------------------
# 400/50: con 250, 400 y 800 tokens la recuperación fue equivalente; sin
# solapamiento baja, porque la respuesta queda partida entre dos fragmentos.
CHUNK_TOKENS = _env("CHUNK_TOKENS", 400, int)
CHUNK_OVERLAP = _env("CHUNK_OVERLAP", 50, int)

# ---- Recuperación -------------------------------------------------------------
# Se buscan RERANKER_CANDIDATOS fragmentos por similitud y el reranker deja TOP_K.
RERANKER_CANDIDATOS = _env("RERANKER_CANDIDATOS", 20, int)
TOP_K = _env("TOP_K", 4, int)
USAR_RERANKER = _env("USAR_RERANKER", True, bool)

# ---- Vector store -------------------------------------------------------------
# «chroma»: índice local en disco. «pgvector»: índice en Supabase, compartido por el
# equipo; la tabla se crea con supabase/migrations/ y se carga con ingesta.indexar.
ALMACEN = _env_opcion("ALMACEN", "chroma", ("chroma", "pgvector"))
# Chroma guarda el índice en disco, dentro del repositorio (carpeta ignorada por git).
RUTA_CHROMA = Path(_env("RUTA_CHROMA", str(RAIZ / "storage" / "chroma")))
# Connection string de Supabase (Project Settings › Database › Connection string,
# «Session pooler», que funciona con IPv4), con la contraseña de la base:
#   postgresql://postgres.<ref>:<contraseña>@aws-0-<región>.pooler.supabase.com:5432/postgres
# Da acceso completo a la base: se guarda con python -m app.rag.secretos guardar
# SUPABASE_DB_URL, que usa el llavero del sistema o, si no hay, .env; nunca va en el
# frontend. Se lee recién al abrir pgvector, para que con Chroma no se consulte el llavero.


def llm_api_key() -> str:
    """
    LLM_API_KEY del entorno (o .env) si está; si no, del llavero.

    Los servidores locales no piden clave, pero el cliente de OpenAI exige una:
    si no está en ninguno, cualquier texto sirve. Se lee recién al crear el
    cliente, para que con Ollama no se consulte el llavero.
    """
    return _env("LLM_API_KEY", "") or secretos.leer("LLM_API_KEY") or "sin-clave"


def supabase_db_url() -> str:
    """SUPABASE_DB_URL del entorno (o .env) si está; si no, del llavero. Vacío si no está en ninguno."""
    return _env("SUPABASE_DB_URL", "") or secretos.leer("SUPABASE_DB_URL") or ""


def clave_servicio() -> str:
    """CLAVE_SERVICIO del entorno (o .env) si está; si no, del llavero. Vacía: la API no pide clave."""
    return _env("CLAVE_SERVICIO", "") or secretos.leer("CLAVE_SERVICIO") or ""


# PGVectorStore le antepone «data_»: la tabla real es public.data_guia_fragmentos.
TABLA_PGVECTOR = _env("TABLA_PGVECTOR", "guia_fragmentos")

# ---- LLM -----------------------------------------------------------------------
# Ollama por defecto. «openai» sirve para cualquier servidor que imite la API de
# OpenAI (LM Studio, llama.cpp, vLLM…), en el mismo equipo o en otro: así, quien
# no puede instalar Ollama prueba con otro programa sin tocar el código.
PROVEEDOR_LLM = _env_opcion("PROVEEDOR_LLM", "ollama", ("ollama", "openai"))
# gemma3:4b ocupa ~3,3 GB. Con un contexto de 8192 tokens, en un Mac de 8 GB con
# bge-m3 y el reranker cargados, Ollama se cae; 4096 alcanza para la pregunta,
# TOP_K fragmentos de 400 tokens y la respuesta.
OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
# Dirección por defecto del servidor local de LM Studio.
LLM_URL = _env("LLM_URL", "http://localhost:1234/v1")
LLM = _env("LLM", "gemma3:4b")
TEMPERATURE = _env("TEMPERATURE", 0.1, float)
CONTEXTO_TOKENS = _env("CONTEXTO_TOKENS", 4096, int)
MAX_TOKENS_RESPUESTA = _env("MAX_TOKENS_RESPUESTA", 768, int)
TIMEOUT_S = _env("TIMEOUT_S", 180, float)
# Lo que el equipo registró del proyecto (asistente por etapa, sugerir.py). El resto de ese
# prompt ocupa unos 1850 tokens con TOP_K=4 (medido con gemma3:4b); 1500 caracteres son unos
# 400 tokens y dejan espacio para la respuesta dentro de CONTEXTO_TOKENS.
MAX_CARACTERES_PROYECTO = _env("MAX_CARACTERES_PROYECTO", 1500, int)

# ---- Umbral y confianza ---------------------------------------------------------
# Sobre el puntaje del reranker (0 a 1). Los fragmentos bajo UMBRAL no llegan al
# LLM y, si no queda ninguno, se responde «No encuentro…» sin llamarlo. La
# confianza se calcula con el mejor puntaje. Calibrados con
# eval/calibrar_umbral.py: si cambia RERANKER, hay que volver a calibrar.
# Con el corpus v3, las preguntas de fuera de la guía llegan como máximo a 0,42 y
# las respondibles parten en 0,72: 0,5 las separa con margen hacia el lado
# seguro (es peor callar una respondible que dejar pasar una de fuera al LLM).
UMBRAL = _env("UMBRAL", 0.5, float)
CONFIANZA_MEDIA = _env("CONFIANZA_MEDIA", 0.7, float)
CONFIANZA_ALTA = _env("CONFIANZA_ALTA", 0.9, float)

# ---- API y simulador ------------------------------------------------------------
# El simulador devuelve respuestas fijas con la forma del contrato y no importa
# LlamaIndex ni los modelos: corre con backend/requirements-simulador.txt en un
# servidor sin GPU (p. ej. Render, plan gratuito), para que la plataforma integre
# la API sin esperar al equipo que tiene los modelos.
MODO = _env_opcion("MODO", "local", ("local", "simulador"))
SIMULADOR_DEMORA_S = _env("SIMULADOR_DEMORA_S", 0.0, float)
# Las consultas se atienden de a una (api.py). Las respuestas reales tardaron entre 89 y
# 298 s en un Mac M2 de 8 GB: con 2 en espera, la última puede esperar unos 10 min. Con
# más en cola conviene responder 503 de inmediato, para que la plataforma reintente más
# tarde en vez de dejar la conexión abierta.
COLA_MAXIMA = _env("COLA_MAXIMA", 2, int)
# Lo que tardó la respuesta más lenta medida (298 s), con margen: alcanza para esperar
# a que termine la consulta en curso. Ajústalo al tiempo de espera de quien llama.
ESPERA_TURNO_S = _env("ESPERA_TURNO_S", 300.0, float)
# Sin precarga, la primera consulta carga los modelos (~1,2 GB cada uno) y tarda más.
# Apagado por defecto: en uso local, uvicorn arranca al instante y los modelos se cargan
# solo si alguien pregunta. En un servidor que atiende a la plataforma, conviene prenderlo.
PRECARGAR = _env("PRECARGAR", False, bool)

# ---- Adjuntos -------------------------------------------------------------------
# La persona sube un PDF, DOCX o MD (app/adjuntos/). Se lee, se seudonimiza y se indexa en
# memoria, separado de la guía; no se guarda en disco ni en Supabase.
# PDF y DOCX es lo acordado con UXLab para el MVP; «md» se puede sumar sin tocar el código.
FORMATOS_ADJUNTO = tuple(f.strip().lower().lstrip(".")
                         for f in _env("FORMATOS_ADJUNTO", "pdf,docx").split(",") if f.strip())
if not FORMATOS_ADJUNTO or set(FORMATOS_ADJUNTO) - set(FORMATOS):
    raise ValueError(f"FORMATOS_ADJUNTO={','.join(FORMATOS_ADJUNTO)!r} no es válido. "
                     f"Usa uno o más de: {', '.join(FORMATOS)}.")
# Provisionales: un entregable de texto pesa bastante menos. Se revisan con la medición del README
# («Adjuntos»). Las páginas pesan más que los MB: Docling tardó ~2 min con las 170 páginas de la
# guía en un Mac M2 de 8 GB, así que 40 páginas son del orden de medio minuto.
MAX_MB_ADJUNTO = _env("MAX_MB_ADJUNTO", 10.0, float)
MAX_PAGINAS_ADJUNTO = _env("MAX_PAGINAS_ADJUNTO", 40, int)
# Sin OCR, un PDF escaneado sale casi vacío: menos de 30 caracteres por página en promedio
# (números de página, algún pie) no alcanza para leerlo. Una página de texto trae más de 1000.
MIN_CARACTERES_PAGINA = _env("MIN_CARACTERES_PAGINA", 30, int)
# Lo que dura una conversación de prueba. Vencido, la persona lo vuelve a subir.
MINUTOS_ADJUNTO = _env("MINUTOS_ADJUNTO", 60.0, float)
# Cada adjunto ocupa poco (unas decenas de fragmentos con vectores de 1024 floats), pero guarda
# datos de personas: se tienen los mínimos en memoria.
MAX_ADJUNTOS = _env("MAX_ADJUNTOS", 5, int)

# ---- Revisión de entregables ----------------------------------------------------
# La revisión (app/revision/) le pasa el documento entero al LLM en cada punto de la rúbrica,
# para que vea todo y Ollama reutilice lo ya procesado. 6000 caracteres son unos 1700 tokens
# de gemma3:4b; con las instrucciones, el punto y la respuesta (~700 tokens) caben en
# CONTEXTO_TOKENS (4096) con margen. Un perfil de una o dos páginas trae 2000 a 4000. Un
# documento más largo se revisa con los TOP_K fragmentos del adjunto más relevantes para cada punto.
MAX_CARACTERES_ENTREGABLE = _env("MAX_CARACTERES_ENTREGABLE", 6000, int)


def coleccion() -> str:
    """
    Nombre de la colección de Chroma para la configuración actual.

    Incluye el corpus, el modelo y la fragmentación (por ejemplo
    «guia_v1_bge-m3_c400o50») para que dos configuraciones no mezclen vectores.
    """
    emb = EMBEDDINGS.split("/")[-1]
    return f"guia_{VERSION_CORPUS}_{emb}_c{CHUNK_TOKENS}o{CHUNK_OVERLAP}"


def url_llm() -> str:
    """Dirección del servidor del LLM según PROVEEDOR_LLM."""
    return OLLAMA_URL if PROVEEDOR_LLM == "ollama" else LLM_URL


def dispositivos() -> list[str] | None:
    """Dispositivos para FlagEmbedding; None le deja elegir (MPS o CUDA si existen, si no CPU)."""
    return [DISPOSITIVO] if DISPOSITIVO else None
