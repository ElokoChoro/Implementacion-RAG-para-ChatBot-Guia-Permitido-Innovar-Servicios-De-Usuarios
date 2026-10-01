"""
Compara modelos de embeddings en la recuperación, con y sin reranker.

Modelos:
  - bge-m3 con FlagEmbedding (el mismo del índice)
  - qwen3-embedding:0.6b y embeddinggemma con Ollama

Todos vectorizan los mismos fragmentos (corpus y fragmentación de config.py) y
responden las preguntas de eval/preguntas_v1.jsonl que tienen sección esperada.
No usa el LLM: solo mide si se recupera el fragmento correcto (métricas en
eval/README.md). Los vectores se comparan en memoria, sin Chroma.

Requisitos: Ollama corriendo con los dos modelos
    ollama pull qwen3-embedding:0.6b && ollama pull embeddinggemma

Uso, desde la raíz del repositorio:
    python eval/comparar_embeddings.py
    SOLO=qwen3,embeddinggemma python eval/comparar_embeddings.py   # algunos modelos

Deja los resultados en eval/resultados/comparacion_embeddings.json (o en SALIDA).
En un Mac de 8 GB conviene cerrar otras aplicaciones: bge-m3 y el reranker ocupan
~1,2 GB cada uno.
"""
from __future__ import annotations

import gc
import json
import os
import sys
import time
import unicodedata
from pathlib import Path
from typing import Callable

import numpy as np
import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "backend"))
from llama_index.core.node_parser import SentenceSplitter  # noqa: E402
from llama_index.core.schema import MetadataMode  # noqa: E402

from app.rag import config  # noqa: E402
from ingesta.indexar import documentos  # noqa: E402

SET = RAIZ / "eval" / "preguntas_v1.jsonl"
SALIDA = Path(os.environ.get("SALIDA", RAIZ / "eval" / "resultados" / "comparacion_embeddings.json"))
OLLAMA = "http://localhost:11434/api/embed"
CANDIDATOS = config.RERANKER_CANDIDATOS  # los que se le pasan al reranker
K = config.TOP_K                         # los que se evalúan al final

Vectorizador = Callable[[list[str]], np.ndarray]


# ---- Datos ---------------------------------------------------------------------
def cargar_fragmentos() -> tuple[list[str], list[dict]]:
    """Fragmentos del corpus igual que en ingesta.indexar: texto a vectorizar y metadatos."""
    splitter = SentenceSplitter(chunk_size=config.CHUNK_TOKENS, chunk_overlap=config.CHUNK_OVERLAP)
    nodos = splitter.get_nodes_from_documents(documentos())
    return [n.get_content(metadata_mode=MetadataMode.EMBED) for n in nodos], [n.metadata for n in nodos]


def cargar_preguntas() -> list[dict]:
    """Preguntas del set con sección esperada (las demás no tienen nada que recuperar)."""
    preguntas = [json.loads(l) for l in SET.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [q for q in preguntas if q["seccion_fuente"]]


# ---- Métricas --------------------------------------------------------------------
def _norm(s: str | None) -> str:
    """Minúsculas y sin tildes, para comparar nombres de sección."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def posicion_seccion(pregunta: dict, fragmentos: list[dict]) -> int | None:
    """Posición (1 = primero) del primer fragmento de la sección esperada; None si no está."""
    esperada = _norm(pregunta["seccion_fuente"])
    for i, f in enumerate(fragmentos, 1):
        if esperada in (_norm(f["actividad"]), _norm(f["herramienta"]), _norm(f["seccion"])):
            return i
    return None


def acierta_pagina(pregunta: dict, fragmentos: list[dict]) -> bool:
    """¿Algún fragmento es de la página esperada?"""
    return any(f["pagina_inicio"] <= pregunta["pagina"] <= f["pagina_fin"] for f in fragmentos)


def metricas(preguntas: list[dict], rankings: list[list[int]], metas: list[dict], k: int) -> dict:
    """Recall por sección, recall por página y MRR mirando los primeros `k` de cada ranking."""
    tops = [[metas[i] for i in r[:k]] for r in rankings]
    posiciones = [posicion_seccion(q, t) for q, t in zip(preguntas, tops)]
    n = len(preguntas)
    return {
        f"recall@{k}": round(100 * sum(p is not None for p in posiciones) / n, 1),
        f"recall_pagina@{k}": round(100 * sum(acierta_pagina(q, t) for q, t in zip(preguntas, tops)) / n, 1),
        f"mrr@{k}": round(sum(1 / p if p else 0 for p in posiciones) / n, 3),
        "fallos": [q["id"] for q, p in zip(preguntas, posiciones) if p is None],
    }


# ---- Modelos -------------------------------------------------------------------
def _ollama(modelo: str, textos: list[str]) -> np.ndarray:
    """Embeddings normalizados de Ollama. `keep_alive: 0` descarga el modelo al terminar."""
    vectores = []
    for i in range(0, len(textos), 16):
        r = requests.post(OLLAMA, json={"model": modelo, "input": textos[i:i + 16], "keep_alive": 0},
                          timeout=600)
        r.raise_for_status()
        vectores += r.json()["embeddings"]
    v = np.array(vectores, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def bge_m3() -> tuple[Vectorizador, Vectorizador]:
    """bge-m3 con la misma clase que usa el índice (sin prefijos)."""
    from app.rag.modelos import EmbeddingBGEM3
    modelo = EmbeddingBGEM3()
    return (lambda xs: np.array(modelo._codificar(xs, consulta=False)),
            lambda xs: np.array(modelo._codificar(xs, consulta=True)))


def qwen3() -> tuple[Vectorizador, Vectorizador]:
    """Qwen3-Embedding: los fragmentos van tal cual; las preguntas, con una instrucción."""
    instruccion = "Instruct: Dada una pregunta, recupera fragmentos de la guía que la respondan\nQuery: "
    return (lambda xs: _ollama("qwen3-embedding:0.6b", xs),
            lambda xs: _ollama("qwen3-embedding:0.6b", [instruccion + x for x in xs]))


def embeddinggemma() -> tuple[Vectorizador, Vectorizador]:
    """EmbeddingGemma: usa los prefijos de tarea que recomienda el modelo."""
    return (lambda xs: _ollama("embeddinggemma", [f"title: none | text: {x}" for x in xs]),
            lambda xs: _ollama("embeddinggemma", [f"task: search result | query: {x}" for x in xs]))


MODELOS: dict[str, Callable[[], tuple[Vectorizador, Vectorizador]]] = {
    "bge-m3 (FlagEmbedding)": bge_m3,
    "qwen3-embedding:0.6b (Ollama)": qwen3,
    "embeddinggemma (Ollama)": embeddinggemma,
}


# ---- Evaluación ------------------------------------------------------------------
def evaluar_embeddings(nombre: str, textos: list[str], metas: list[dict],
                       preguntas: list[dict]) -> tuple[dict, list[list[int]]]:
    """Recupera por similitud coseno y mide; devuelve el resultado y los candidatos de cada pregunta."""
    t0 = time.time()
    vectorizar_doc, vectorizar_preg = MODELOS[nombre]()
    carga = time.time() - t0
    t0 = time.time()
    docs = vectorizar_doc(textos)
    indexar = time.time() - t0
    t0 = time.time()
    preg = vectorizar_preg([q["pregunta"] for q in preguntas])
    consulta = (time.time() - t0) / len(preguntas)

    rankings = [list(np.argsort(-fila)[:CANDIDATOS]) for fila in preg @ docs.T]
    resultado = {
        "dim": int(docs.shape[1]), "carga_s": round(carga, 1), "indexar_s": round(indexar, 1),
        "consulta_ms": round(1000 * consulta),
        "denso": {**metricas(preguntas, rankings, metas, K),
                  f"recall@{CANDIDATOS}": metricas(preguntas, rankings, metas, CANDIDATOS)[f"recall@{CANDIDATOS}"]},
    }
    return resultado, rankings


def reordenar(preguntas: list[dict], rankings: list[list[int]], textos: list[str]) -> list[list[int]]:
    """Reordena los candidatos de cada pregunta con el reranker del módulo."""
    from app.rag.modelos import reordenador
    modelo = reordenador()._modelo
    nuevos = []
    for q, candidatos in zip(preguntas, rankings):
        puntajes = modelo.compute_score([(q["pregunta"], textos[i]) for i in candidatos], normalize=True)
        nuevos.append([candidatos[j] for j in np.argsort(-np.array(puntajes))])
    return nuevos


def main():
    textos, metas = cargar_fragmentos()
    preguntas = cargar_preguntas()
    print(f"{len(textos)} fragmentos · {len(preguntas)} preguntas con sección esperada", flush=True)

    elegidos = list(MODELOS)
    if os.environ.get("SOLO"):
        elegidos = [m for m in MODELOS if any(x in m for x in os.environ["SOLO"].split(","))]

    # Primero todos los embeddings y después el reranker, para no tener todos los
    # modelos en memoria a la vez.
    resultados, candidatos = {}, {}
    for nombre in elegidos:
        print(f"\n== {nombre}", flush=True)
        resultados[nombre], candidatos[nombre] = evaluar_embeddings(nombre, textos, metas, preguntas)
        print(json.dumps(resultados[nombre], ensure_ascii=False), flush=True)
        gc.collect()

    print(f"\n== reranker {config.RERANKER}", flush=True)
    for nombre, rankings in candidatos.items():
        t0 = time.time()
        reordenados = reordenar(preguntas, rankings, textos)
        resultados[nombre]["reranker"] = metricas(preguntas, reordenados, metas, K)
        resultados[nombre]["reranker_ms"] = round(1000 * (time.time() - t0) / len(preguntas))
        print(nombre, json.dumps(resultados[nombre]["reranker"], ensure_ascii=False), flush=True)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(resultados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n-> {SALIDA}")


if __name__ == "__main__":
    main()
