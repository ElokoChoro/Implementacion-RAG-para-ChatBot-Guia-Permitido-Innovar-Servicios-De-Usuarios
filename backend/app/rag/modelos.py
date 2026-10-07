"""
Modelos locales de FlagEmbedding adaptados a LlamaIndex.

EmbeddingBGEM3
    Vectoriza textos con BAAI/bge-m3 (vectores densos de 1024 dimensiones,
    normalizados). Es un `BaseEmbedding`, así que LlamaIndex lo usa igual al
    indexar la guía y al vectorizar la pregunta. Tiene que ser el mismo modelo
    en ambos casos: si cambia, hay que volver a indexar.

ReordenadorBGE
    Reordena fragmentos con BAAI/bge-reranker-v2-m3. A diferencia del embedding,
    que compara vectores calculados por separado, el reranker lee la pregunta y
    el fragmento juntos (cross-encoder): es más preciso, pero más lento, por eso
    solo se aplica a unos pocos candidatos. Es un `BaseNodePostprocessor`.

llm()
    El LLM que redacta la respuesta (gemma3:4b por defecto). No corre en este
    proceso: es un cliente de Ollama (`ollama pull gemma3:4b`) o, con
    PROVEEDOR_LLM=openai, de un servidor compatible con la API de OpenAI, como
    LM Studio. El servidor puede estar en otro equipo.

Cargar cada modelo de FlagEmbedding tarda varios segundos y ocupa ~1,2 GB en
fp16. Usar `embedding()`, `reordenador()` y `llm()`, que crean una sola
instancia por proceso.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from FlagEmbedding import BGEM3FlagModel, FlagReranker
from llama_index.core.bridge.pydantic import Field, PrivateAttr
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.llms import LLM
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle

from app.rag import config


class EmbeddingBGEM3(BaseEmbedding):
    """
    Embeddings densos de bge-m3.

    Los vectores salen normalizados, así que la similitud coseno equivale al
    producto punto. bge-m3 no usa prefijos ni instrucciones: preguntas y
    fragmentos se vectorizan tal cual, cada uno con su largo máximo.
    """

    max_length: int = Field(default=config.MAX_TOKENS_EMBEDDING,
                            description="Tokens máximos por texto; lo que sobra se trunca.")
    _modelo: BGEM3FlagModel = PrivateAttr()

    def __init__(self, model_name: str = config.EMBEDDINGS, **kwargs: Any) -> None:
        kwargs.setdefault("embed_batch_size", 8)  # lotes chicos: menos memoria en equipos de 8 GB
        super().__init__(model_name=model_name, **kwargs)
        self._modelo = BGEM3FlagModel(model_name, use_fp16=config.FP16,
                                      devices=config.dispositivos(),
                                      normalize_embeddings=True)

    @classmethod
    def class_name(cls) -> str:
        return "EmbeddingBGEM3"

    def _codificar(self, textos: list[str], consulta: bool) -> list[list[float]]:
        """Vectoriza `textos` como preguntas (`consulta=True`) o como fragmentos de la guía."""
        codificar = self._modelo.encode_queries if consulta else self._modelo.encode_corpus
        salida = codificar(textos, batch_size=self.embed_batch_size, max_length=self.max_length)
        return salida["dense_vecs"].tolist()

    # Métodos que exige BaseEmbedding. Las versiones async llaman a las síncronas:
    # FlagEmbedding no tiene API asíncrona.
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
    Reordena los fragmentos candidatos con bge-reranker-v2-m3 y deja los `top_n` mejores.

    El puntaje de cada fragmento se reemplaza por el del reranker, normalizado
    entre 0 y 1 con una sigmoide. Sirve como medida de certeza: si todos los
    fragmentos quedan cerca de 0, la guía probablemente no responde la pregunta.
    """

    top_n: int = Field(default=config.TOP_K, description="Fragmentos que se devuelven.")
    _modelo: FlagReranker = PrivateAttr()

    def __init__(self, model_name: str = config.RERANKER, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._modelo = FlagReranker(model_name, use_fp16=config.FP16,
                                    devices=config.dispositivos(),
                                    max_length=config.MAX_TOKENS_RERANKER)

    @classmethod
    def class_name(cls) -> str:
        return "ReordenadorBGE"

    def reordenar(self, nodos: list[NodeWithScore], pregunta: str, top_n: int) -> list[NodeWithScore]:
        """
        Los `top_n` fragmentos más relevantes para `pregunta`, con el puntaje del reranker.

        Recibe `top_n` en cada llamada en vez de leer `self.top_n`: la instancia es
        compartida (reordenador()) y cambiarle el atributo afectaría a otra consulta.
        """
        if not nodos:
            return []
        # Cada fragmento se puntúa con el mismo texto que se vectorizó, que
        # incluye su «fuente» (sección › herramienta, p. N).
        pares = [(pregunta, n.node.get_content(metadata_mode=MetadataMode.EMBED)) for n in nodos]
        puntajes = self._modelo.compute_score(pares, normalize=True)
        if isinstance(puntajes, float):  # con un solo par, FlagReranker devuelve un número
            puntajes = [puntajes]
        for n, puntaje in zip(nodos, puntajes, strict=True):
            n.score = float(puntaje)
        return sorted(nodos, key=lambda n: n.score, reverse=True)[:top_n]

    def _postprocess_nodes(self, nodes: list[NodeWithScore],
                           query_bundle: QueryBundle | None = None) -> list[NodeWithScore]:
        # Para usarlo como postprocesador de LlamaIndex, con self.top_n.
        if query_bundle is None:
            raise ValueError("El reranker necesita la pregunta (query_bundle).")
        return self.reordenar(nodes, query_bundle.query_str, self.top_n)


@lru_cache(maxsize=1)
def embedding() -> EmbeddingBGEM3:
    """Instancia compartida del modelo de embeddings (se carga la primera vez que se pide)."""
    return EmbeddingBGEM3()


@lru_cache(maxsize=1)
def reordenador() -> ReordenadorBGE:
    """Instancia compartida del reranker (se carga la primera vez que se pide)."""
    return ReordenadorBGE()


@lru_cache(maxsize=1)
def llm() -> LLM:
    """Cliente compartido del LLM según PROVEEDOR_LLM, con la temperatura y los límites de config."""
    if config.PROVEEDOR_LLM == "ollama":
        from llama_index.llms.ollama import Ollama
        return Ollama(model=config.LLM, base_url=config.OLLAMA_URL,
                      temperature=config.TEMPERATURE,
                      context_window=config.CONTEXTO_TOKENS,  # se envía como num_ctx
                      request_timeout=config.TIMEOUT_S,
                      additional_kwargs={"num_predict": config.MAX_TOKENS_RESPUESTA})
    if config.PROVEEDOR_LLM == "openai":
        from llama_index.llms.openai_like import OpenAILike
        # context_window no viaja al servidor: LlamaIndex lo usa para saber cuánto cabe.
        # Sin reintentos, para que TIMEOUT_S sea la espera total, como con Ollama.
        return OpenAILike(model=config.LLM, api_base=config.LLM_URL, api_key=config.llm_api_key(),
                          temperature=config.TEMPERATURE,
                          context_window=config.CONTEXTO_TOKENS,
                          max_tokens=config.MAX_TOKENS_RESPUESTA,
                          timeout=config.TIMEOUT_S, max_retries=0,
                          is_chat_model=True, is_function_calling_model=False)
    raise ValueError(f"PROVEEDOR_LLM={config.PROVEEDOR_LLM!r} no existe. Usa «ollama» u «openai».")
