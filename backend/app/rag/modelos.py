"""
Modelos locales de FlagEmbedding como componentes de LlamaIndex (ADR-01, ADR-04):

  EmbeddingBGEM3  -> BAAI/bge-m3, vectores densos de 1024 dimensiones.
                     Se usa igual al indexar la guía y al vectorizar la pregunta.
  ReordenadorBGE  -> BAAI/bge-reranker-v2-m3, cross-encoder que puntúa cada par
                     (pregunta, fragmento) y deja los TOP_K más relevantes.

Los pesos se descargan de Hugging Face la primera vez y luego corren sin red.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from FlagEmbedding import BGEM3FlagModel, FlagReranker
from llama_index.core.bridge.pydantic import Field, PrivateAttr
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle

from app.rag import config


class EmbeddingBGEM3(BaseEmbedding):
    """Embeddings densos de bge-m3 (normalizados: coseno = producto punto)."""

    max_length: int = Field(default=config.MAX_TOKENS_EMBEDDING)
    _modelo: BGEM3FlagModel = PrivateAttr()

    def __init__(self, model_name: str = config.EMBEDDINGS, **kwargs: Any) -> None:
        kwargs.setdefault("embed_batch_size", 8)
        super().__init__(model_name=model_name, **kwargs)
        self._modelo = BGEM3FlagModel(model_name, use_fp16=config.FP16,
                                      devices=config.dispositivos(),
                                      normalize_embeddings=True)

    @classmethod
    def class_name(cls) -> str:
        return "EmbeddingBGEM3"

    def _codificar(self, textos: list[str], consulta: bool) -> list[list[float]]:
        codificar = self._modelo.encode_queries if consulta else self._modelo.encode_corpus
        salida = codificar(textos, batch_size=self.embed_batch_size, max_length=self.max_length)
        return salida["dense_vecs"].tolist()

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._codificar([query], consulta=True)[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._codificar([text], consulta=False)[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._codificar(texts, consulta=False)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)


class ReordenadorBGE(BaseNodePostprocessor):
    """
    Reordena los candidatos con bge-reranker-v2-m3 y deja los `top_n` mejores.
    El puntaje queda normalizado entre 0 y 1 (sigmoide), útil como certeza.
    """

    top_n: int = Field(default=config.TOP_K)
    _modelo: FlagReranker = PrivateAttr()

    def __init__(self, model_name: str = config.RERANKER, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._modelo = FlagReranker(model_name, use_fp16=config.FP16,
                                    devices=config.dispositivos(),
                                    max_length=config.MAX_TOKENS_RERANKER)

    @classmethod
    def class_name(cls) -> str:
        return "ReordenadorBGE"

    def _postprocess_nodes(self, nodes: list[NodeWithScore],
                           query_bundle: QueryBundle | None = None) -> list[NodeWithScore]:
        if query_bundle is None:
            raise ValueError("El reranker necesita la pregunta (query_bundle).")
        if not nodes:
            return []
        # El fragmento se puntúa con el mismo texto que se vectorizó (incluye la «fuente»).
        pares = [(query_bundle.query_str, n.node.get_content(metadata_mode=MetadataMode.EMBED))
                 for n in nodes]
        puntajes = self._modelo.compute_score(pares, normalize=True)
        if isinstance(puntajes, float):  # un solo par devuelve un número
            puntajes = [puntajes]
        for n, puntaje in zip(nodes, puntajes):
            n.score = float(puntaje)
        return sorted(nodes, key=lambda n: n.score, reverse=True)[: self.top_n]


# Cargar un modelo tarda y ocupa ~1,2 GB cada uno en fp16: una instancia por proceso.
@lru_cache(maxsize=1)
def embedding() -> EmbeddingBGEM3:
    return EmbeddingBGEM3()


@lru_cache(maxsize=1)
def reordenador() -> ReordenadorBGE:
    return ReordenadorBGE()
