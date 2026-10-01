"""
Índice vectorial de la guía.

Los fragmentos y sus vectores se guardan en Chroma, en disco (config.RUTA_CHROMA),
con distancia coseno. El índice se crea con `python -m ingesta.indexar`; este
módulo solo lo abre.
"""
from __future__ import annotations

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.rag import config
from app.rag.modelos import embedding


def vector_store(reiniciar: bool = False) -> ChromaVectorStore:
    """
    Abre (o crea) la colección de Chroma de la configuración actual.

    Con `reiniciar=True` borra la colección antes, para indexar desde cero.
    """
    cliente = chromadb.PersistentClient(path=str(config.RUTA_CHROMA))
    if reiniciar and config.coleccion() in [c.name for c in cliente.list_collections()]:
        cliente.delete_collection(config.coleccion())
    col = cliente.get_or_create_collection(config.coleccion(), metadata={"hnsw:space": "cosine"})
    return ChromaVectorStore(chroma_collection=col)


def indice() -> VectorStoreIndex:
    """
    Índice de LlamaIndex sobre la colección existente, con el modelo de embeddings
    que vectoriza las preguntas.

    Lanza RuntimeError si la colección está vacía (todavía no se indexó).
    """
    vs = vector_store()
    if vs._collection.count() == 0:
        raise RuntimeError(f"La colección «{config.coleccion()}» está vacía. "
                           "Ejecuta desde la raíz:  python -m ingesta.indexar")
    return VectorStoreIndex.from_vector_store(vs, embed_model=embedding())
