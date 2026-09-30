"""Índice vectorial de la guía en Chroma local (transición de la demo, ADR-07)."""
from __future__ import annotations

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.rag import config
from app.rag.modelos import embedding


def vector_store(reiniciar: bool = False) -> ChromaVectorStore:
    cliente = chromadb.PersistentClient(path=str(config.RUTA_CHROMA))
    if reiniciar and config.coleccion() in [c.name for c in cliente.list_collections()]:
        cliente.delete_collection(config.coleccion())
    col = cliente.get_or_create_collection(config.coleccion(), metadata={"hnsw:space": "cosine"})
    return ChromaVectorStore(chroma_collection=col)


def indice() -> VectorStoreIndex:
    vs = vector_store()
    if vs._collection.count() == 0:
        raise RuntimeError(f"La colección «{config.coleccion()}» está vacía. "
                           "Ejecuta desde la raíz:  python -m ingesta.indexar")
    return VectorStoreIndex.from_vector_store(vs, embed_model=embedding())
