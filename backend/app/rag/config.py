"""
Configuración del módulo RAG.

Cada valor se puede cambiar con una variable de entorno del mismo nombre, sin
tocar el código. Por ejemplo, para recuperar 6 fragmentos a partir de 30
candidatos:

    TOP_K=6 RERANKER_CANDIDATOS=30 python -m app.rag.recuperar "¿Qué es un plano del servicio?"

Variables disponibles
---------------------
VERSION_CORPUS         Versión del corpus en data/corpus/ (por defecto «v2»).
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
                       Es una credencial: va en el llavero del sistema (ver secretos.py);
                       la variable de entorno solo se usa donde no hay llavero (CI, servidor).
TABLA_PGVECTOR         Tabla del índice en pgvector, sin el prefijo «data_» de PGVectorStore.
OLLAMA_URL             Dirección del servidor de Ollama.
LLM                    Modelo de Ollama que redacta la respuesta («gemma3:4b»).
TEMPERATURE            Aleatoriedad del LLM; baja para que se apegue a la guía.
CONTEXTO_TOKENS        Ventana de contexto del LLM (num_ctx de Ollama).
MAX_TOKENS_RESPUESTA   Largo máximo de la respuesta, en tokens (num_predict de Ollama).
TIMEOUT_S              Segundos de espera a Ollama antes de dar error.
UMBRAL                 Puntaje mínimo del reranker (0 a 1) para que un fragmento llegue al LLM.
CONFIANZA_MEDIA        Mejor puntaje desde el que la confianza es «media».
CONFIANZA_ALTA         Mejor puntaje desde el que la confianza es «alta».

Si cambian EMBEDDINGS, CHUNK_TOKENS, CHUNK_OVERLAP o VERSION_CORPUS, hay que
volver a indexar (python -m ingesta.indexar). En Chroma cada combinación usa su
propia colección (ver `coleccion()`), así que los índices anteriores no se pisan.
En pgvector hay una sola tabla, que se recarga completa al indexar.

Las variables también se leen del archivo .env de la raíz del repositorio (ver
.env.example); las que ya están definidas en el entorno tienen prioridad. Las
credenciales no van en .env sino en el llavero del sistema (ver secretos.py).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

from app.rag import secretos

RAIZ = Path(__file__).resolve().parents[3]  # raíz del repositorio
load_dotenv(RAIZ / ".env")


def _env(nombre: str, defecto, tipo=str):
    """Lee una variable de entorno y la convierte a `tipo`; si falta o está vacía, usa `defecto`."""
    valor = os.getenv(nombre)
    if valor in (None, ""):
        return defecto
    if tipo is bool:
        return valor.strip().lower() in ("1", "true", "si", "sí")
    return tipo(valor)


# ---- Corpus -------------------------------------------------------------------
# El corpus es el texto de la guía ya extraído y dividido en páginas con sus
# metadatos. Se versiona en el repositorio; el PDF original no.
VERSION_CORPUS = _env("VERSION_CORPUS", "v2")
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
ALMACEN = _env("ALMACEN", "chroma")
# Chroma guarda el índice en disco, dentro del repositorio (carpeta ignorada por git).
RUTA_CHROMA = Path(_env("RUTA_CHROMA", str(RAIZ / "storage" / "chroma")))
# Connection string de Supabase (Project Settings › Database › Connection string,
# «Session pooler», que funciona con IPv4), con la contraseña de la base:
#   postgresql://postgres.<ref>:<contraseña>@aws-0-<región>.pooler.supabase.com:5432/postgres
# Da acceso completo a la base: se guarda en el llavero del sistema
# (python -m app.rag.secretos guardar SUPABASE_DB_URL), nunca en el frontend. Se lee
# recién al abrir pgvector, para que con Chroma no se consulte el llavero.


def supabase_db_url() -> str:
    """SUPABASE_DB_URL del entorno (o .env) si está; si no, del llavero. Vacío si no está en ninguno."""
    return _env("SUPABASE_DB_URL", "") or secretos.leer("SUPABASE_DB_URL") or ""


# PGVectorStore le antepone «data_»: la tabla real es public.data_guia_fragmentos.
TABLA_PGVECTOR = _env("TABLA_PGVECTOR", "guia_fragmentos")

# ---- LLM local (Ollama) ---------------------------------------------------------
# gemma3:4b ocupa ~3,3 GB. Con un contexto de 8192 tokens, en un Mac de 8 GB con
# bge-m3 y el reranker cargados, Ollama se cae; 4096 alcanza para la pregunta,
# TOP_K fragmentos de 400 tokens y la respuesta.
OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
LLM = _env("LLM", "gemma3:4b")
TEMPERATURE = _env("TEMPERATURE", 0.1, float)
CONTEXTO_TOKENS = _env("CONTEXTO_TOKENS", 4096, int)
MAX_TOKENS_RESPUESTA = _env("MAX_TOKENS_RESPUESTA", 768, int)
TIMEOUT_S = _env("TIMEOUT_S", 180, float)

# ---- Umbral y confianza ---------------------------------------------------------
# Sobre el puntaje del reranker (0 a 1). Los fragmentos bajo UMBRAL no llegan al
# LLM y, si no queda ninguno, se responde «No encuentro…» sin llamarlo. La
# confianza se calcula con el mejor puntaje. Calibrados con
# eval/calibrar_umbral.py: si cambia RERANKER, hay que volver a calibrar.
# Con el corpus v2, las preguntas de fuera de la guía llegan como máximo a 0,40 y
# las respondibles parten en 0,72: 0,5 las separa con margen hacia el lado
# seguro (es peor callar una respondible que dejar pasar una de fuera al LLM).
UMBRAL = _env("UMBRAL", 0.5, float)
CONFIANZA_MEDIA = _env("CONFIANZA_MEDIA", 0.7, float)
CONFIANZA_ALTA = _env("CONFIANZA_ALTA", 0.9, float)


def coleccion() -> str:
    """
    Nombre de la colección de Chroma para la configuración actual.

    Incluye el corpus, el modelo y la fragmentación (por ejemplo
    «guia_v1_bge-m3_c400o50») para que dos configuraciones no mezclen vectores.
    """
    emb = EMBEDDINGS.split("/")[-1]
    return f"guia_{VERSION_CORPUS}_{emb}_c{CHUNK_TOKENS}o{CHUNK_OVERLAP}"


def dispositivos() -> list[str] | None:
    """Dispositivos para FlagEmbedding; None le deja elegir (MPS o CUDA si existen, si no CPU)."""
    return [DISPOSITIVO] if DISPOSITIVO else None
