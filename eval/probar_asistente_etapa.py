"""
Prueba el prompt del asistente por etapa (app.rag.sugerir) con los escenarios de
eval/escenarios_etapa_v1.jsonl: un proyecto ficticio en cada una de las 7
etapas, más dos intentos de inyección en el contexto del proyecto.

Por cada escenario genera la respuesta con el LLM y revisa, sin juez humano:

  formato        trae las tres partes del formato y entre 3 y 5 pasos
  citas_validas_llm  % de citas [entre corchetes] que copian una línea «fuente:»
                 de los fragmentos del prompt, como las escribió el LLM;
                 None si no cita
  citas_validas  lo mismo, después de ajustar_citas (lo que devuelve sugerir)
  herramienta    nombra alguna herramienta de la etapa (guia.py)
  esperado       nombra lo que el escenario pide en «menciona» y nada de lo que
                 está en «no_menciona» (por ejemplo, lo que pide la inyección)

También anota los tokens del prompt según el servidor del LLM, para ver cuánto margen queda
en CONTEXTO_TOKENS. Las revisiones son automáticas y gruesas: no miden si los
pasos son buenos, solo si respetan el formato y la guía. Conviene leer las
respuestas en el JSON de salida.

Uso, desde la raíz del repositorio (índice construido y el servidor del LLM corriendo):
    python eval/probar_asistente_etapa.py
    python eval/probar_asistente_etapa.py --ids E-04 E-08
    python eval/probar_asistente_etapa.py --recalcular   # revisa de nuevo el JSON, sin LLM

Deja los resultados en eval/resultados/asistente_etapa.json (o en SALIDA).
Con gemma3:4b en un Mac M2 de 8 GB tarda ~1,5 min por escenario. Con DISPOSITIVO=cpu
bge-m3 y el reranker dejan la GPU a Ollama; en mps el reranker se quedó sin memoria.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
from app.rag import config, guia  # noqa: E402
from app.rag.flujo import tokens  # noqa: E402
from app.rag.modelos import llm  # noqa: E402
from app.rag.prompts import MENSAJE_NO_ENCONTRADA  # noqa: E402
from app.rag.prompts_etapa import VERSION_PROMPT_ETAPA  # noqa: E402
from app.rag.sugerir import (  # noqa: E402
    ajustar_citas,
    fragmentos,
    fuentes_prompt,
    limpiar_citas,
    mensajes,
    texto_proyecto,
)

ESCENARIOS = RAIZ / "eval" / "escenarios_etapa_v1.jsonl"
SALIDA = Path(os.environ.get("SALIDA", RAIZ / "eval" / "resultados" / "asistente_etapa.json"))
PARTES = ["**Qué busca esta etapa:**", "**Próximos pasos:**", "**Herramienta sugerida:**"]


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.replace("–", "-").replace("—", "-")).strip().lower()


def citas(texto: str) -> list[str]:
    """Citas entre corchetes; «[A; B]» cuenta como dos."""
    return [c.strip() for grupo in re.findall(r"\[([^\[\]]+)\]", texto)
            for c in grupo.split(";") if c.strip()]


def pasos(texto: str) -> int:
    """Viñetas de la parte «Próximos pasos»."""
    bloque = texto.split(PARTES[1], 1)[-1].split(PARTES[2], 1)[0]
    return len(re.findall(r"^\s*(?:[-*•]|\d+[.)])\s+", bloque, flags=re.MULTILINE))


def _validas(cs: list[str], fuentes: set[str]) -> list[str]:
    normalizadas = {_normalizar(f) for f in fuentes}
    return [c for c in cs if _normalizar(c) in normalizadas]


def revisar(esc: dict, fila: dict) -> dict:
    """Revisiones automáticas de una respuesta; `fila` trae respuesta_llm y fuentes_prompt."""
    fuentes = set(fila["fuentes_prompt"])
    texto = ajustar_citas(limpiar_citas(fila["respuesta_llm"]), fuentes)
    bajo = texto.lower()
    cs_llm, cs = citas(fila["respuesta_llm"]), citas(texto)
    validas = _validas(cs, fuentes)
    n_pasos = pasos(texto)
    herramientas = [nombre for _, nombre in guia.etapa(esc["etapa"]).herramientas]
    faltan = [m for m in esc["menciona"] if m.lower() not in bajo]
    sobran = [m for m in esc["no_menciona"] if m.lower() in bajo]
    return {
        "respuesta": texto,
        "rechazo": texto.startswith(MENSAJE_NO_ENCONTRADA),
        "formato": all(p in texto for p in PARTES) and 3 <= n_pasos <= 5,
        "pasos": n_pasos,
        "citas": len(cs),
        "citas_validas_llm": round(100 * len(_validas(cs_llm, fuentes)) / len(cs_llm), 1) if cs_llm else None,
        "citas_validas": round(100 * len(validas) / len(cs), 1) if cs else None,
        "citas_invalidas": [c for c in cs if c not in validas],
        "herramienta": any(h.lower() in bajo for h in herramientas),
        "esperado": not faltan and not sobran,
        "faltan": faltan,
        "sobran": sobran,
    }


def generar(esc: dict) -> dict:
    """Respuesta del LLM para un escenario, con lo necesario para revisarla."""
    t0 = time.time()
    nodos, mejor = fragmentos(esc["etapa"])
    ms = mensajes(esc["etapa"], nodos, texto_proyecto(esc["contexto"], esc["datos_etapa"]))
    r = llm().chat(ms)
    uso = tokens(r)
    return {
        "id": esc["id"], "etapa": esc["etapa"], "descripcion": esc["descripcion"],
        "respuesta_llm": limpiar_citas((r.message.content or "").strip()),
        "fuentes_prompt": sorted(fuentes_prompt(nodos)),
        "mejor_puntaje": mejor,
        "tokens_prompt": uso.prompt,
        "tokens_respuesta": uso.respuesta,
        "latencia_s": round(time.time() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="*", help="solo estos escenarios")
    ap.add_argument("--recalcular", action="store_true",
                    help="revisa de nuevo las respuestas guardadas en SALIDA, sin llamar al LLM")
    args = ap.parse_args()

    escenarios = [json.loads(linea) for linea in ESCENARIOS.read_text(encoding="utf-8").splitlines() if linea.strip()]
    if args.ids:
        escenarios = [e for e in escenarios if e["id"] in args.ids]
    previo = json.loads(SALIDA.read_text(encoding="utf-8")) if args.recalcular else None
    guardadas = {f["id"]: f for f in previo["escenarios"]} if previo else {}

    filas = []
    for e in escenarios:
        if args.recalcular and e["id"] not in guardadas:
            continue
        g = guardadas[e["id"]] if args.recalcular else generar(e)
        claves = ["id", "etapa", "descripcion", "respuesta_llm", "fuentes_prompt", "mejor_puntaje",
                  "tokens_prompt", "tokens_respuesta", "latencia_s"]
        f = {k: g[k] for k in claves} | revisar(e, g)
        filas.append(f)
        print(f"{f['id']} etapa {f['etapa']}: formato {f['formato']} · pasos {f['pasos']} · "
              f"citas {f['citas']} ({f['citas_validas_llm']} % válidas del LLM, "
              f"{f['citas_validas']} % tras ajustar) · herramienta {f['herramienta']} · "
              f"esperado {f['esperado']} · {f['tokens_prompt']} tokens · {f['latencia_s']} s")
        print("     " + f["respuesta"].replace("\n", "\n     "))
        for c in f["citas_invalidas"]:
            print(f"     cita inválida: [{c}]")
        if f["faltan"] or f["sobran"]:
            print(f"     faltan {f['faltan']} · sobran {f['sobran']}")

    def pct(clave):
        return round(100 * sum(bool(f[clave]) for f in filas) / len(filas), 1)

    def promedio(clave):
        vs = [f[clave] for f in filas if f[clave] is not None]
        return round(sum(vs) / len(vs), 1) if vs else None

    resumen = {
        "escenarios": len(filas),
        "formato": pct("formato"),
        "herramienta": pct("herramienta"),
        "esperado": pct("esperado"),
        "rechazos": sum(f["rechazo"] for f in filas),
        "citas_por_respuesta": round(sum(f["citas"] for f in filas) / len(filas), 1),
        "citas_validas_llm": promedio("citas_validas_llm"),
        "citas_validas": promedio("citas_validas"),
        "tokens_prompt_max": max((f["tokens_prompt"] or 0) for f in filas),
        "latencia_s_promedio": round(sum(f["latencia_s"] for f in filas) / len(filas), 1),
    }
    print(json.dumps(resumen, ensure_ascii=False, indent=2))

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({
        "fecha": previo["fecha"] if previo else time.strftime("%Y-%m-%d"),
        "config": {"llm": config.LLM, "prompt": VERSION_PROMPT_ETAPA, "top_k": config.TOP_K,
                   "umbral": config.UMBRAL, "contexto_tokens": config.CONTEXTO_TOKENS,
                   "corpus": config.coleccion()},
        "resumen": resumen,
        "escenarios": filas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultados en {SALIDA}")


if __name__ == "__main__":
    main()
