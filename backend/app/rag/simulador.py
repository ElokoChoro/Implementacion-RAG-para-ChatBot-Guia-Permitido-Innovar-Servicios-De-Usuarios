"""
Simulador de `POST /ia/consultar-guia`: respuestas fijas, sin modelos (MODO=simulador).

Sirve para que la plataforma integre la API antes de tener los modelos a mano:
devuelve una `Respuesta` (contrato.py) con los mismos campos, la misma
validación y los mismos errores que generar.py, pero no importa LlamaIndex,
FlagEmbedding ni el cliente del LLM. Así corre en cualquier servidor con
backend/requirements-simulador.txt (fastapi, uvicorn y python-dotenv).

Respuestas
----------
Hay tres, armadas a partir de respuestas reales del sistema (corpus v2, prompt
v4, gemma3:4b, 2026-10-05), con el formato de cita que pide el prompt y
fragmentos acortados. Con `etapa` 1, 2 o 7 se devuelve la de esa etapa; con
cualquier otra, o sin etapa, la del plano del servicio (etapa 7). La pregunta
no cambia el texto: el simulador no busca en la guía.

Marcas para probar cada caso (en cualquier parte de la pregunta):
    #no-encontrada     la guía no responde: encontrada=false, confianza null, sin fuentes
    #confianza-media   respuesta con confianza «media»
    #confianza-baja    respuesta con confianza «baja»
    #error             503, como cuando el servidor del LLM no está disponible
Sin marca, la respuesta tiene confianza «alta». SIMULADOR_DEMORA_S agrega una
espera, para probar los tiempos de espera de quien llama (las respuestas reales
tardaron entre 89 y 298 s en un Mac M2 de 8 GB).

Prueba rápida, desde backend/:
    python -m app.rag.simulador "¿Qué es un plano del servicio?"
    python -m app.rag.simulador "¿Cuánto cuesta? #no-encontrada" --etapa 1
"""
from __future__ import annotations

import argparse
import json
import time

from app.rag import config
from app.rag.contrato import Respuesta
from app.rag.prompts import MENSAJE_NO_ENCONTRADA, SUGERENCIA

# Mejor puntaje del reranker para cada confianza simulada, dentro de los cortes
# por defecto (CONFIANZA_ALTA 0,9 y CONFIANZA_MEDIA 0,7; UMBRAL 0,5).
PUNTAJES = {"alta": 0.95, "media": 0.8, "baja": 0.6}
# Bajo UMBRAL: así queda el mejor puntaje cuando la guía no responde.
PUNTAJE_NO_ENCONTRADA = 0.3


def _fuente(seccion: str, pagina: int, fuente: str, fragmento: str, puntaje: float) -> dict:
    return {"seccion": seccion, "pagina": pagina, "fuente": fuente, "fragmento": fragmento, "puntaje": puntaje}


RESPUESTAS = {
    7: ("El plano del servicio es una de las herramientas más utilizadas para implementar iniciativas en el diseño "
        "de servicios. Ayuda a analizar la situación actual y a proyectar la experiencia que se quiere ofrecer, con "
        "un enfoque sistémico que une la perspectiva usuaria y la organizacional "
        "[Modelo operativo › Plano del servicio, p. 122]. Se estructura en capas de información asociadas a las "
        "interacciones: primero se anotan las acciones de las personas usuarias y luego los puntos de contacto en "
        "que ocurren [Modelo operativo › Plano del servicio, p. 122].",
        [_fuente("Plano del servicio", 124, "Modelo operativo › Plano del servicio, p. 124",
                 "CASO DE APLICACIÓN: PLANO DEL SERVICIO\n\n## NUEVO MODELO DE ATENCIÓN FONASA…", 0.936),
         _fuente("Plano del servicio", 122, "Modelo operativo › Plano del servicio, p. 122",
                 "## PLANO DEL SERVICIO\n\n## ¿PARA QUÉ SIRVE?\n\nEsta herramienta es una de las más utilizadas "
                 "para la implementación de iniciativas en el diseño de servicios…", 0.874)]),
    1: ("La guía propone el Plan de investigación de experiencia usuaria, que permite planificar de forma ordenada "
        "y realista una investigación cualitativa centrada en la experiencia "
        "[Investigación › Plan de investigación de experiencia usuaria, p. 110].",
        [_fuente("Plan de investigación de experiencia usuaria", 110,
                 "Investigación › Plan de investigación de experiencia usuaria, p. 110",
                 "## PLAN DE INVESTIGACIÓN DE EXPERIENCIA USUARIA\n\n## ¿PARA QUÉ SIRVE?\n\nEsta herramienta "
                 "permite planificar de forma ordenada y realista una investigación cualitativa…", 0.995),
         _fuente("Investigación", 109, "Investigación, p. 109",
                 "## ¿CUÁNDO DESARROLLARLA?\n\nEsta actividad se lleva a cabo de manera óptima al inicio de un "
                 "proyecto de experiencia…", 0.888)]),
    2: ("El Mapa de perfiles de personas usuarias sirve para explorar y representar la diversidad de grupos de "
        "personas que interactúan con un servicio. Busca identificar patrones y diferencias en su forma de "
        "relacionarse con el servicio para construir una tipología de perfiles; también se puede aplicar a PEC y "
        "personas funcionarias [Personas › Mapa de perfiles de personas usuarias, p. 142].",
        [_fuente("Mapa de perfiles de personas usuarias", 142,
                 "Personas › Mapa de perfiles de personas usuarias, p. 142",
                 "## MAPA DE PERFILES DE PERSONAS USUARIAS\n\n## ¿PARA QUÉ SIRVE?\n\nEsta herramienta les "
                 "permitirá explorar y representar la diversidad de grupos de personas…", 1.0),
         _fuente("Personas", 141, "Personas, p. 141",
                 "## ¿CUÁNDO DESARROLLARLA?\n\nSe recomienda aplicar esta actividad una vez que se dispone de "
                 "hallazgos recogidos a partir de la Investigación…", 0.994)]),
}
ETAPA_POR_DEFECTO = 7


def responder(pregunta: str, etapa: int | None = None, filtrar_etapa: bool = False) -> Respuesta:
    """
    Respuesta fija con la forma de generar.responder(); la elige `etapa` y la ajustan las marcas.

    `filtrar_etapa` se acepta para tener la misma firma, pero no cambia nada.
    Lanza RuntimeError con la marca #error, como generar.py cuando el LLM no responde.
    """
    t0 = time.time()
    if config.SIMULADOR_DEMORA_S > 0:
        time.sleep(config.SIMULADOR_DEMORA_S)
    marcas = pregunta.lower()
    comunes = {"modelo": "simulador", "modo": "simulador"}

    if "#error" in marcas:
        raise RuntimeError("Simulador: error pedido con #error. Con los modelos, aquí llega el motivo "
                           "(por ejemplo, que el servidor del LLM no está disponible).")
    if "#no-encontrada" in marcas:
        return Respuesta(resultado=f"{MENSAJE_NO_ENCONTRADA} {SUGERENCIA}", encontrada=False, confianza=None,
                         puntaje=PUNTAJE_NO_ENCONTRADA, latencia_s=round(time.time() - t0, 1), **comunes)

    nivel = "media" if "#confianza-media" in marcas else "baja" if "#confianza-baja" in marcas else "alta"
    puntaje = PUNTAJES[nivel]
    texto, fuentes = RESPUESTAS.get(etapa or ETAPA_POR_DEFECTO, RESPUESTAS[ETAPA_POR_DEFECTO])
    # Ninguna fuente supera al mejor puntaje, como en una respuesta real.
    fuentes = [{**f, "puntaje": min(f["puntaje"], puntaje)} for f in fuentes]
    return Respuesta(resultado=texto, encontrada=True, confianza=nivel, fuentes=fuentes, puntaje=puntaje,
                     latencia_s=round(time.time() - t0, 1), **comunes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta")
    ap.add_argument("--etapa", type=int, help="etapa del proyecto (1-7): elige la respuesta fija")
    args = ap.parse_args()
    print(json.dumps(responder(args.pregunta, args.etapa).a_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
