"""
EXP-08: compara modelos de embeddings, con y sin reranker, solo en recuperación.

  bge-m3 (FlagEmbedding, el del índice) · qwen3-embedding:0.6b y embeddinggemma (Ollama)

Mismos fragmentos (corpus v1, 400/50) y mismas métricas que evaluar.py del
laboratorio (recall por sección, recall por página, MRR), con el set v1.
Requiere Ollama con los dos modelos:  ollama pull qwen3-embedding:0.6b && ollama pull embeddinggemma

    python eval/comparar_embeddings.py
    SOLO=qwen3,embeddinggemma python eval/comparar_embeddings.py   # algunos modelos

En un Mac de 8 GB, cerrar otras aplicaciones: bge-m3 y el reranker ocupan ~1,2 GB cada uno.
"""
import gc, json, os, sys, time, unicodedata
from pathlib import Path
import numpy as np, requests, torch

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ)); sys.path.insert(0, str(RAIZ / "backend"))
from ingesta.indexar import documentos  # noqa
from app.rag import config  # noqa
from llama_index.core.node_parser import SentenceSplitter  # noqa
from llama_index.core.schema import MetadataMode  # noqa

SET = RAIZ / "eval" / "preguntas_v1.jsonl"
OLLAMA = "http://localhost:11434/api/embed"
N_CAND, K = 20, 4

nodos = SentenceSplitter(chunk_size=400, chunk_overlap=50).get_nodes_from_documents(documentos())
textos = [n.get_content(metadata_mode=MetadataMode.EMBED) for n in nodos]
metas = [n.metadata for n in nodos]
preguntas = [json.loads(l) for l in SET.read_text().splitlines() if l.strip()]
preguntas = [q for q in preguntas if q["seccion_fuente"]]  # igual que evaluar.py --solo-recuperacion
print(f"{len(nodos)} fragmentos · {len(preguntas)} preguntas con fuente", flush=True)


def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def rango(q, frags):
    obj = _norm(q["seccion_fuente"])
    for i, f in enumerate(frags, 1):
        if obj in (_norm(f["actividad"]), _norm(f["herramienta"]), _norm(f["seccion"])):
            return i
    return None


def hit_pag(q, frags):
    return any(f["pagina_inicio"] <= q["pagina"] <= f["pagina_fin"] for f in frags)


def metricas(listas, k):
    r = [rango(q, [metas[i] for i in l[:k]]) for q, l in zip(preguntas, listas)]
    return {f"recall@{k}": round(100 * sum(x is not None for x in r) / len(r), 1),
            f"recall_pagina@{k}": round(100 * sum(hit_pag(q, [metas[i] for i in l[:k]])
                                                  for q, l in zip(preguntas, listas)) / len(r), 1),
            f"mrr@{k}": round(sum(1 / x if x else 0 for x in r) / len(r), 3),
            "fallos": [q["id"] for q, x in zip(preguntas, r) if x is None]}


def ollama(modelo, xs):
    out = []
    for i in range(0, len(xs), 16):
        resp = requests.post(OLLAMA, json={"model": modelo, "input": xs[i:i + 16], "keep_alive": 0}, timeout=600)
        resp.raise_for_status()
        out += resp.json()["embeddings"]
    v = np.array(out, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def bge_m3():
    from app.rag.modelos import EmbeddingBGEM3
    m = EmbeddingBGEM3()
    return (lambda xs: np.array(m._codificar(xs, consulta=False)),
            lambda xs: np.array(m._codificar(xs, consulta=True)), m)


TAREA_QWEN = "Instruct: Dada una pregunta, recupera fragmentos de la guía que la respondan\nQuery: "
MODELOS = {
    "bge-m3 (FlagEmbedding)": bge_m3,
    "qwen3-embedding:0.6b (Ollama)": lambda: (
        lambda xs: ollama("qwen3-embedding:0.6b", xs),
        lambda xs: ollama("qwen3-embedding:0.6b", [TAREA_QWEN + x for x in xs]), None),
    "embeddinggemma (Ollama)": lambda: (
        lambda xs: ollama("embeddinggemma", [f"title: none | text: {x}" for x in xs]),
        lambda xs: ollama("embeddinggemma", [f"task: search result | query: {x}" for x in xs]), None),
}

SOLO = os.environ.get("SOLO")
if SOLO:
    MODELOS = {k: v for k, v in MODELOS.items() if any(x in k for x in SOLO.split(","))}
resultados, candidatos = {}, {}
for nombre, crear in MODELOS.items():
    print(f"\n== {nombre}", flush=True)
    t0 = time.time(); doc_fn, q_fn, ref = crear(); t_carga = time.time() - t0
    t0 = time.time(); D = doc_fn(textos); t_idx = time.time() - t0
    t0 = time.time(); Q = q_fn([q["pregunta"] for q in preguntas]); t_q = (time.time() - t0) / len(preguntas)
    S = Q @ D.T
    listas = [list(np.argsort(-s)[:N_CAND]) for s in S]
    candidatos[nombre] = listas
    resultados[nombre] = {"dim": D.shape[1], "carga_s": round(t_carga, 1), "indexar_s": round(t_idx, 1),
                          "consulta_ms": round(1000 * t_q), "denso": {**metricas(listas, K), **{
                              k: v for k, v in metricas(listas, N_CAND).items() if k.startswith("recall@")}}}
    print(json.dumps(resultados[nombre], ensure_ascii=False), flush=True)
    del ref; gc.collect(); torch.mps.empty_cache() if torch.backends.mps.is_available() else None

print("\n== reranker bge-reranker-v2-m3", flush=True)
from app.rag.modelos import ReordenadorBGE  # noqa
rr = ReordenadorBGE()._modelo
for nombre, listas in candidatos.items():
    t0 = time.time(); nuevas = []
    for q, l in zip(preguntas, listas):
        p = rr.compute_score([(q["pregunta"], textos[i]) for i in l], normalize=True)
        nuevas.append([l[j] for j in np.argsort(-np.array(p))])
    resultados[nombre]["reranker"] = metricas(nuevas, K)
    resultados[nombre]["reranker_ms"] = round(1000 * (time.time() - t0) / len(preguntas))
    print(nombre, json.dumps(resultados[nombre]["reranker"], ensure_ascii=False), flush=True)

Path(os.environ.get("SALIDA", RAIZ / "eval" / "resultados" / "exp08_embeddings.json")).write_text(json.dumps(resultados, ensure_ascii=False, indent=1))
