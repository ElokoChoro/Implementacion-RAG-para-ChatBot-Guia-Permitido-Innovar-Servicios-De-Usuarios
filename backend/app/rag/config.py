"""
Configuración del módulo RAG.

Cada valor se puede cambiar con una variable de entorno del mismo nombre, sin
tocar el código. Por ejemplo, para recuperar 6 fragmentos a partir de 30
candidatos:

    TOP_K=6 RERANKER_CANDIDATOS=30 python -m app.rag.recuperar "¿Qué es un plano del servicio?"

Variables disponibles
---------------------
VERSION_CORPUS         Versión del corpus en data/corpus/ (por defecto «v1»).
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
RUTA_CHROMA            Carpeta donde Chroma guarda el índice.

Si cambian EMBEDDINGS, CHUNK_TOKENS, CHUNK_OVERLAP o VERSION_CORPUS, hay que
volver a indexar (python -m ingesta.indexar). Cada combinación usa su propia
colección (ver `coleccion()`), así que los índices anteriores no se pisan.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]  # raíz del repositorio


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
VERSION_CORPUS = _env("VERSION_CORPUS", "v1")
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
# Chroma guarda el índice en disco, dentro del repositorio (carpeta ignorada por git).
RUTA_CHROMA = Path(_env("RUTA_CHROMA", str(RAIZ / "storage" / "chroma")))


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
