"""
Paso 3 de la ingesta: fragmenta el corpus, lo vectoriza y lo guarda en el
vector store de ALMACEN (Chroma local o pgvector en Supabase).

Cada página se divide con el SentenceSplitter de LlamaIndex (CHUNK_TOKENS con
CHUNK_OVERLAP de solapamiento, sin cortar oraciones) y cada fragmento se
vectoriza con bge-m3. Los fragmentos heredan los metadatos de su página.

El índice se vacía y se reconstruye desde cero en cada ejecución, así siempre
corresponde al corpus versionado:

    python -m ingesta.indexar                     # Chroma local
    ALMACEN=pgvector python -m ingesta.indexar    # Supabase (antes, aplicar la migración)

La primera vez descarga BAAI/bge-m3 (~2,3 GB) desde Hugging Face.

Si el índice ya está en Chroma, se puede copiar a pgvector con los mismos
vectores, sin cargar el modelo (los dos índices quedan idénticos):

    ALMACEN=pgvector python -m ingesta.indexar --desde-chroma
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode

from app.rag import config
from app.rag.indice import contar, descripcion, vector_store
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
        # Corpus, modelo y fragmentación con que se cargó; en pgvector, donde hay
        # una sola tabla, sirve para avisar si la consulta usa otra configuración.
        meta["indice"] = config.coleccion()
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


def fragmentos_de_chroma() -> list[BaseNode]:
    """Fragmentos, con su vector, de la colección de Chroma de la configuración actual."""
    import chromadb
    from llama_index.core.vector_stores.utils import metadata_dict_to_node

    cliente = chromadb.PersistentClient(path=str(config.RUTA_CHROMA))
    if config.coleccion() not in [c.name for c in cliente.list_collections()]:
        sys.exit(f"No existe la colección «{config.coleccion()}» en {config.RUTA_CHROMA}. "
                 "Indexa primero en Chroma (python -m ingesta.indexar) o quita --desde-chroma.")
    datos = cliente.get_collection(config.coleccion()).get(include=["embeddings", "metadatas", "documents"])
    nodos = []
    for vector, meta, texto in zip(datos["embeddings"], datos["metadatas"], datos["documents"], strict=True):
        nodo = metadata_dict_to_node(meta, text=texto)
        nodo.embedding = [float(x) for x in vector]
        # Las colecciones creadas antes de existir «indice» no lo traen
        nodo.metadata["indice"] = config.coleccion()
        for ocultas in (nodo.excluded_embed_metadata_keys, nodo.excluded_llm_metadata_keys):
            if "indice" not in ocultas:
                ocultas.append("indice")
        nodos.append(nodo)
    return nodos


def main():
    """Fragmenta, vectoriza y guarda todo el corpus en un índice vacío."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde-chroma", action="store_true",
                    help="copia los vectores de la colección de Chroma en vez de recalcularlos (con ALMACEN=pgvector)")
    args = ap.parse_args()

    t0 = time.time()
    if args.desde_chroma:
        if config.ALMACEN == "chroma":
            sys.exit("--desde-chroma copia de Chroma a otro almacén: usa ALMACEN=pgvector.")
        nodos = fragmentos_de_chroma()
        vector_store(reiniciar=True).add(nodos)
        origen = f"{len(nodos)} fragmentos de Chroma"
    else:
        docs = documentos()
        splitter = SentenceSplitter(chunk_size=config.CHUNK_TOKENS, chunk_overlap=config.CHUNK_OVERLAP)
        VectorStoreIndex.from_documents(
            docs,
            storage_context=StorageContext.from_defaults(vector_store=vector_store(reiniciar=True)),
            embed_model=embedding(),
            transformations=[splitter],
            show_progress=True,
        )
        origen = f"{len(docs)} páginas"
    n = contar(vector_store())
    print(f"«{config.coleccion()}»: {origen} -> {n} fragmentos "
          f"en {time.time() - t0:.0f} s ({descripcion()})")


if __name__ == "__main__":
    main()
