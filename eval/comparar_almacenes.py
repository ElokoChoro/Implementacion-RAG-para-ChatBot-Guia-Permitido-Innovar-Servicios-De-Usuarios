"""
Compara la recuperación por similitud de Chroma y pgvector (Supabase).

Para cada pregunta de eval/preguntas_v1.jsonl con sección esperada recupera los
RERANKER_CANDIDATOS fragmentos más similares en cada almacén, sin reranker (el
reranker no depende del almacén), y compara:

  coinciden_top_k     % de preguntas con los mismos TOP_K fragmentos, en el mismo orden
  coinciden_candidatos % de preguntas con el mismo conjunto de candidatos para el reranker
  dif_max_distancia   mayor diferencia de distancia coseno entre fragmentos iguales
  recall/MRR          métricas de eval/README.md en cada almacén

Si los dos índices tienen los mismos vectores (ingesta.indexar --desde-chroma),
deberían coincidir salvo empates. El índice HNSW de pgvector es aproximado, pero
con unos 200 fragmentos casi no hay diferencia.

Se comparan distancias y no puntajes porque cada librería los escala distinto:
ChromaVectorStore entrega exp(-distancia) y PGVectorStore, 1 - distancia.

Uso, desde la raíz del repositorio (los dos índices tienen que existir y
SUPABASE_DB_URL tiene que estar en el llavero o en .env; ver app/rag/secretos.py):
    python eval/comparar_almacenes.py

Deja los resultados en eval/resultados/comparacion_almacenes.json (o en SALIDA).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "backend"))
from app.rag import config  # noqa: E402
from app.rag.recuperar import recuperar  # noqa: E402
from eval.comparar_embeddings import cargar_preguntas, metricas  # noqa: E402

SALIDA = Path(os.environ.get("SALIDA", RAIZ / "eval" / "resultados" / "comparacion_almacenes.json"))
ALMACENES = ("chroma", "pgvector")
CANDIDATOS = config.RERANKER_CANDIDATOS
K = config.TOP_K


def distancia(almacen: str, puntaje: float) -> float:
    """Distancia coseno a partir del puntaje que entrega el vector store de LlamaIndex."""
    return -math.log(puntaje) if almacen == "chroma" else 1 - puntaje


def recuperar_en(almacen: str,
                 preguntas: list[dict]) -> tuple[list[list[str]], dict[str, dict], dict[str, list[float]], float]:
    """Ids y distancias de los CANDIDATOS de cada pregunta, y los metadatos de cada id."""
    config.ALMACEN = almacen
    ids, metas, distancias = [], {}, {}
    t0 = time.time()
    for q in preguntas:
        nodos = recuperar(q["pregunta"], top_k=CANDIDATOS, usar_reranker=False)
        ids.append([n.node.node_id for n in nodos])
        distancias[q["id"]] = [distancia(almacen, n.score) for n in nodos]
        metas.update({n.node.node_id: n.node.metadata for n in nodos})
    return ids, metas, distancias, (time.time() - t0) / len(preguntas)


def main():
    preguntas = cargar_preguntas()
    print(f"{len(preguntas)} preguntas · {config.coleccion()} · {CANDIDATOS} candidatos, top {K}", flush=True)

    res = {}
    for almacen in ALMACENES:
        ids, metas, distancias, seg = recuperar_en(almacen, preguntas)
        # metricas() trabaja con posiciones en una lista de metadatos
        orden = list(metas)
        rankings = [[orden.index(i) for i in r] for r in ids]
        lista = [metas[i] for i in orden]
        res[almacen] = {"ids": ids, "distancias": distancias, "s_por_pregunta": round(seg, 2),
                        **metricas(preguntas, rankings, lista, K),
                        **{k: v for k, v in metricas(preguntas, rankings, lista, CANDIDATOS).items()
                           if k.startswith("recall@")}}
        print(f"{almacen:<9} recall@{K} {res[almacen][f'recall@{K}']} · mrr@{K} {res[almacen][f'mrr@{K}']} · "
              f"recall@{CANDIDATOS} {res[almacen][f'recall@{CANDIDATOS}']} · {seg:.2f} s/pregunta", flush=True)

    a, b = (res[x]["ids"] for x in ALMACENES)
    iguales_k = [x[:K] == y[:K] for x, y in zip(a, b, strict=True)]
    iguales_cand = [set(x) == set(y) for x, y in zip(a, b, strict=True)]
    dif = 0.0
    for q, x, y in zip(preguntas, a, b, strict=True):
        pa = dict(zip(x, res["chroma"]["distancias"][q["id"]], strict=True))
        pb = dict(zip(y, res["pgvector"]["distancias"][q["id"]], strict=True))
        dif = max([dif, *(abs(pa[i] - pb[i]) for i in pa.keys() & pb.keys())])
    resumen = {
        f"coinciden_top{K}": round(100 * sum(iguales_k) / len(preguntas), 1),
        "coinciden_candidatos": round(100 * sum(iguales_cand) / len(preguntas), 1),
        "dif_max_distancia": round(dif, 6),
        "distintas": [q["id"] for q, ok in zip(preguntas, iguales_k, strict=True) if not ok],
    }
    print(f"\nMismos top {K}: {resumen[f'coinciden_top{K}']} % · mismos candidatos: "
          f"{resumen['coinciden_candidatos']} % · diferencia máxima de distancia: {dif:.6f}")
    if resumen["distintas"]:
        print(f"Preguntas con otro top {K}: {', '.join(resumen['distintas'])}")

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({
        "fecha": time.strftime("%Y-%m-%d"), "coleccion": config.coleccion(),
        "candidatos": CANDIDATOS, "top_k": K, "resumen": resumen,
        **{x: {k: v for k, v in res[x].items() if k not in ("ids", "distancias")} for x in ALMACENES},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"-> {SALIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
