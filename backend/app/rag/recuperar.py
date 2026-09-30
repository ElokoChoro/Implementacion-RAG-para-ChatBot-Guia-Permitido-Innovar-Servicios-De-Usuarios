"""
Recuperación en dos pasos:
  1. bge-m3 busca los RERANKER_CANDIDATOS fragmentos más parecidos (coseno).
  2. bge-reranker-v2-m3 los vuelve a puntuar leyendo pregunta y fragmento juntos
     y deja los TOP_K mejores.

Prueba rápida desde backend/:
    python -m app.rag.recuperar "¿Qué es un mapa de momentos críticos?" --etapa 7
"""
from __future__ import annotations

import argparse
import time

from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters

from app.rag import config
from app.rag.indice import indice
from app.rag.modelos import reordenador


def _filtros(etapa: int | None) -> MetadataFilters | None:
    if not etapa:
        return None
    return MetadataFilters(filters=[MetadataFilter(key="etapa", value=etapa,
                                                   operator=FilterOperator.EQ)])


def recuperar(pregunta: str, etapa: int | None = None, top_k: int = config.TOP_K,
              usar_reranker: bool = config.USAR_RERANKER) -> list[NodeWithScore]:
    """Fragmentos de la guía más relevantes para la pregunta, del mejor al peor."""
    candidatos = config.RERANKER_CANDIDATOS if usar_reranker else top_k
    retriever = indice().as_retriever(similarity_top_k=max(candidatos, top_k),
                                      filters=_filtros(etapa))
    nodos = retriever.retrieve(pregunta)
    if not usar_reranker:
        return nodos
    reranker = reordenador()
    reranker.top_n = top_k
    return reranker.postprocess_nodes(nodos, query_bundle=QueryBundle(pregunta))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta")
    ap.add_argument("--etapa", type=int, help="filtra por etapa (1-7)")
    ap.add_argument("-k", type=int, default=config.TOP_K)
    ap.add_argument("--sin-reranker", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    nodos = recuperar(args.pregunta, args.etapa, args.k, not args.sin_reranker)
    print(f"{len(nodos)} fragmentos en {time.time() - t0:.1f} s ({config.coleccion()})\n")
    for i, n in enumerate(nodos, 1):
        texto = n.node.get_content().replace("\n", " ")
        print(f"{i}. [{n.score:.3f}] {n.node.metadata['fuente']}\n   {texto[:220]}…\n")


if __name__ == "__main__":
    main()
