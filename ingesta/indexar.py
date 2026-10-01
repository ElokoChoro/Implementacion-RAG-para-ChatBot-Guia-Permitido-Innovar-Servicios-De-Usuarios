"""
Paso 3 de la ingesta: fragmenta el corpus y lo vectoriza en Chroma.

Cada página se divide con el SentenceSplitter de LlamaIndex (CHUNK_TOKENS con
CHUNK_OVERLAP de solapamiento, sin cortar oraciones) y cada fragmento se
vectoriza con bge-m3. Los fragmentos heredan los metadatos de su página.

La colección se borra y se reconstruye desde cero en cada ejecución, así el
índice siempre corresponde al corpus versionado:

    python -m ingesta.indexar

La primera vez descarga BAAI/bge-m3 (~2,3 GB) desde Hugging Face.
"""
from __future__ import annotations

import json
import sys
import time

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

from app.rag import config
from app.rag.indice import vector_store
from app.rag.modelos import embedding

# Metadatos que se guardan con cada fragmento (Chroma no acepta None)
CLAVES = ["fuente", "seccion", "actividad", "herramienta", "etapa",
          "pagina_inicio", "pagina_fin", "version_corpus"]


def documentos() -> list[Document]:
    """Una página del corpus por Document de LlamaIndex, con sus metadatos."""
    if not config.RUTA_PAGINAS.exists():
        sys.exit(f"Falta {config.RUTA_PAGINAS.relative_to(config.RAIZ)}. Ejecuta primero:  python -m ingesta.corpus")
    docs = []
    for linea in config.RUTA_PAGINAS.read_text(encoding="utf-8").splitlines():
        r = json.loads(linea)
        meta = {k: r[k] for k in CLAVES}
        meta["etapa"] = meta["etapa"] or 0  # 0 = sin etapa
        ocultas = [k for k in meta if k != "fuente"]
        docs.append(Document(
            id_=r["id"], text=r["texto"], metadata=meta,
            # Solo «fuente» (sección › herramienta, p. N) entra al texto que se
            # vectoriza, al que ve el reranker y al que ve el LLM; el resto sirve
            # para filtrar y citar.
            excluded_embed_metadata_keys=ocultas,
            excluded_llm_metadata_keys=ocultas,
        ))
    return docs


def main():
    """Fragmenta, vectoriza y guarda todo el corpus en una colección nueva."""
    docs = documentos()
    splitter = SentenceSplitter(chunk_size=config.CHUNK_TOKENS, chunk_overlap=config.CHUNK_OVERLAP)
    t0 = time.time()
    VectorStoreIndex.from_documents(
        docs,
        storage_context=StorageContext.from_defaults(vector_store=vector_store(reiniciar=True)),
        embed_model=embedding(),
        transformations=[splitter],
        show_progress=True,
    )
    n = vector_store()._collection.count()
    print(f"Colección «{config.coleccion()}»: {len(docs)} páginas -> {n} fragmentos "
          f"en {time.time() - t0:.0f} s ({config.RUTA_CHROMA})")


if __name__ == "__main__":
    main()
