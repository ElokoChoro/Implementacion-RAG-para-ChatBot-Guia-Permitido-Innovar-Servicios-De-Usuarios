"""
Calibra el umbral de rechazo y los cortes de confianza sobre el puntaje del reranker.

Para cada pregunta de eval/preguntas_v1.jsonl recupera los TOP_K fragmentos con
el reranker (igual que app.rag.generar, sin filtro por etapa) y anota sus
puntajes (0 a 1). No usa el LLM. Después prueba varios umbrales:

  rechazo_fuera       % de preguntas «fuera» de la guía en que ningún fragmento
                      llega al umbral, así que se responde «No encuentro…» sin LLM
  falsos_no_encuentro % de preguntas «respondible» que el umbral dejaría sin respuesta
  recall              % de respondibles con algún fragmento de la sección esperada
                      sobre el umbral (lo que le llega al LLM)

Muestra el hueco entre la pregunta de fuera con mayor puntaje y la respondible
con menor puntaje, y los umbrales que no se equivocan en ninguna. Dentro de ese
rango conviene quedarse cerca del lado de las de fuera: es mejor que una llegue
al LLM, que todavía puede rechazarla, a callar una que la guía sí responde. Para
la confianza muestra, por franja del mejor puntaje, qué % de respondibles tiene
la sección esperada en el primer lugar.

Uso, desde la raíz del repositorio (el índice tiene que existir):
    python eval/calibrar_umbral.py

Deja los resultados en eval/resultados/umbral.json (o en SALIDA). Los puntajes
dependen del reranker: si cambia RERANKER, hay que volver a calibrar.
"""
from __future__ import annotations

import json
import os
import sys
import time
from itertools import pairwise
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "backend"))
from app.rag import config  # noqa: E402
from app.rag.recuperar import recuperar  # noqa: E402
from eval.comparar_embeddings import SET, posicion_seccion  # noqa: E402

SALIDA = Path(os.environ.get("SALIDA", RAIZ / "eval" / "resultados" / "umbral.json"))
UMBRALES = [0.0, 0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
FRANJAS = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.01]  # para los cortes de confianza


def puntuar(preguntas: list[dict]) -> list[dict]:
    """Puntajes del reranker de los TOP_K fragmentos de cada pregunta, del mejor al peor."""
    filas = []
    for i, q in enumerate(preguntas, 1):
        nodos = recuperar(q["pregunta"], top_k=config.TOP_K, usar_reranker=True)
        metas = [n.node.metadata for n in nodos]
        filas.append({
            "id": q["id"], "categoria": q["categoria"], "pregunta": q["pregunta"],
            "puntajes": [round(n.score, 4) for n in nodos],
            "fuentes": [m["fuente"] for m in metas],
            # Posición de la sección esperada entre los TOP_K (None si no está o no tiene)
            "pos_seccion": posicion_seccion(q, metas) if q["seccion_fuente"] else None,
        })
        print(f"{i:>2}/{len(preguntas)} {q['id']} {q['categoria']:<11} "
              f"mejor={filas[-1]['puntajes'][0]:.3f}  {filas[-1]['fuentes'][0]}", flush=True)
    return filas


def _pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def _pasa(f: dict, umbral: float) -> bool:
    """El mejor fragmento supera el umbral, así que la pregunta llega al LLM."""
    return f["puntajes"][0] >= umbral


def _recupera(f: dict, umbral: float) -> bool:
    """La sección esperada está entre los fragmentos que superan el umbral."""
    return f["pos_seccion"] is not None and f["puntajes"][f["pos_seccion"] - 1] >= umbral


def barrer(filas: list[dict]) -> list[dict]:
    """Métricas de rechazo y recuperación para cada umbral de UMBRALES."""
    respondibles = [f for f in filas if f["categoria"] == "respondible"]
    fuera = [f for f in filas if f["categoria"] == "fuera"]
    ambiguas = [f for f in filas if f["categoria"] == "ambigua"]
    tabla = []
    for u in UMBRALES:
        tabla.append({
            "umbral": u,
            "rechazo_fuera": _pct(sum(not _pasa(f, u) for f in fuera), len(fuera)),
            "falsos_no_encuentro": _pct(sum(not _pasa(f, u) for f in respondibles), len(respondibles)),
            "recall": _pct(sum(_recupera(f, u) for f in respondibles), len(respondibles)),
            "ambiguas_rechazadas": sum(not _pasa(f, u) for f in ambiguas),
        })
    return tabla


def franjas(filas: list[dict]) -> list[dict]:
    """Por franja del mejor puntaje: cuántas respondibles caen ahí y cuántas tienen la sección primero."""
    respondibles = [f for f in filas if f["categoria"] == "respondible"]
    salida = []
    for lo, hi in pairwise(FRANJAS):
        en = [f for f in respondibles if lo <= f["puntajes"][0] < hi]
        salida.append({"desde": lo, "hasta": min(hi, 1.0), "respondibles": len(en),
                       "seccion_primera": _pct(sum(f["pos_seccion"] == 1 for f in en), len(en)),
                       "fuera": sum(lo <= f["puntajes"][0] < hi for f in filas if f["categoria"] == "fuera")})
    return salida


def main():
    preguntas = [json.loads(linea) for linea in SET.read_text(encoding="utf-8").splitlines() if linea.strip()]
    print(f"{len(preguntas)} preguntas · {config.coleccion()} · reranker {config.RERANKER}", flush=True)
    t0 = time.time()
    filas = puntuar(preguntas)
    tabla = barrer(filas)
    # Umbrales que rechazan todas las de fuera sin callar ninguna respondible
    sin_errores = [t["umbral"] for t in tabla
                   if t["falsos_no_encuentro"] == 0 and t["rechazo_fuera"] == 100]

    print("\numbral  rechazo_fuera  falsos_no_encuentro  recall  ambiguas_rechazadas")
    for t in tabla:
        print(f"{t['umbral']:>6.2f}  {t['rechazo_fuera']:>13}  {t['falsos_no_encuentro']:>19}"
              f"  {t['recall']:>6}  {t['ambiguas_rechazadas']:>19}")
    print("\nmejor puntaje   respondibles  sección primero (%)  fuera")
    for f in franjas(filas):
        print(f"{f['desde']:.1f}–{f['hasta']:.1f}  {f['respondibles']:>17}  "
              f"{f['seccion_primera']:>19}  {f['fuera']:>5}")
    menor = min((f for f in filas if f["categoria"] == "respondible"), key=lambda f: f["puntajes"][0])
    mayor = max((f for f in filas if f["categoria"] == "fuera"), key=lambda f: f["puntajes"][0])
    print(f"\nRespondible con el menor puntaje: {menor['id']} {menor['puntajes'][0]:.3f}")
    print(f"Fuera de la guía con el mayor puntaje: {mayor['id']} {mayor['puntajes'][0]:.3f}")
    if sin_errores:
        print(f"Umbrales sin errores: {min(sin_errores)} a {max(sin_errores)} (actual: {config.UMBRAL})")
    else:
        print(f"Ningún umbral separa todas las preguntas (actual: {config.UMBRAL})")
    print(f"{time.time() - t0:.0f} s")

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({
        "coleccion": config.coleccion(), "reranker": config.RERANKER, "top_k": config.TOP_K,
        "candidatos": config.RERANKER_CANDIDATOS, "umbrales_sin_errores": sin_errores,
        "barrido": tabla, "franjas": franjas(filas), "preguntas": filas,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"-> {SALIDA}")


if __name__ == "__main__":
    main()
