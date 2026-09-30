"""
Configuración del módulo RAG. Todo se puede cambiar con variables de entorno,
sin tocar el código:

    TOP_K=6 RERANKER_CANDIDATOS=30 python -m app.rag.recuperar "¿Qué es un plano del servicio?"
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]  # raíz del repositorio


def _env(nombre, defecto, tipo=str):
    valor = os.getenv(nombre)
    if valor in (None, ""):
        return defecto
    if tipo is bool:
        return valor.strip().lower() in ("1", "true", "si", "sí")
    return tipo(valor)


# ---- Corpus (ADR-06, ADR-11) -------------------------------------------------
VERSION_CORPUS = _env("VERSION_CORPUS", "v1")
RUTA_PAGINAS = RAIZ / "data" / "corpus" / VERSION_CORPUS / "paginas.jsonl"

# ---- Modelos locales (FlagEmbedding) -----------------------------------------
EMBEDDINGS = _env("EMBEDDINGS", "BAAI/bge-m3")
EMBEDDINGS_DIM = 1024  # dimensión de bge-m3; fija la columna de pgvector (ADR-07)
RERANKER = _env("RERANKER", "BAAI/bge-reranker-v2-m3")
# "cpu", "mps" (Apple Silicon) o "cuda:0". Vacío = FlagEmbedding elige.
DISPOSITIVO = _env("DISPOSITIVO", "")
# fp16 ahorra la mitad de memoria; en CPU FlagEmbedding lo ignora.
FP16 = _env("FP16", True, bool)
# Tokens máximos (tokenizador XLM-R de bge-m3). Un fragmento de 400 tokens
# tiktoken más la pregunta cabe de sobra en 1024.
MAX_TOKENS_EMBEDDING = _env("MAX_TOKENS_EMBEDDING", 1024, int)
MAX_TOKENS_RERANKER = _env("MAX_TOKENS_RERANKER", 1024, int)

# ---- Chunking (EXP-04) --------------------------------------------------------
CHUNK_TOKENS = _env("CHUNK_TOKENS", 400, int)
CHUNK_OVERLAP = _env("CHUNK_OVERLAP", 50, int)

# ---- Recuperación ------------------------------------------------------------
# Se buscan RERANKER_CANDIDATOS fragmentos por similitud y el reranker deja TOP_K.
RERANKER_CANDIDATOS = _env("RERANKER_CANDIDATOS", 20, int)
TOP_K = _env("TOP_K", 4, int)
USAR_RERANKER = _env("USAR_RERANKER", True, bool)

# ---- Vector store (Chroma local para la demo, ver ADR-07) --------------------
RUTA_CHROMA = Path(_env("RUTA_CHROMA", str(RAIZ / "storage" / "chroma")))


def coleccion() -> str:
    """Una colección por corpus, modelo y chunking, para no mezclar índices."""
    emb = EMBEDDINGS.split("/")[-1]
    return f"guia_{VERSION_CORPUS}_{emb}_c{CHUNK_TOKENS}o{CHUNK_OVERLAP}"


def dispositivos() -> list[str] | None:
    return [DISPOSITIVO] if DISPOSITIVO else None
