"""
Prompt del asistente: un mensaje de sistema con las reglas y un mensaje de
usuario con la etapa, los fragmentos recuperados y la pregunta.

Versiones:
  v1  Primera versión: citar, no inventar, rechazar con una frase fija y
      terminar con el nivel de certeza.
  v2  Con gemma3:4b, v1 copiaba el formato literal de la cita («[Sección, p. N]»),
      no pedía aclaración ante preguntas ambiguas y mezclaba la frase de rechazo
      con contenido inventado. v2 obliga a decidir antes entre responder, pedir
      aclaración o rechazar; la frase de rechazo va al inicio y la cita se copia
      de la línea «fuente:» de cada fragmento.
  v3  v2 sin la regla de terminar con la certeza: la confianza la calcula el
      backend con el puntaje del reranker (ver generar.py).
  v4  (vigente) El mensaje de usuario trae el contexto de la etapa y no solo su
      nombre: propósito, actividad de la guía, objetivo y herramientas, desde
      guia.py, para que el caso B se resuelva con la herramienta de la etapa.
      Sin etapa, el mensaje queda igual que en v3 («no indicada»). SISTEMA no
      cambia. Ojo: las preguntas ambiguas («¿cómo hago el mapa?») suelen quedar
      bajo el UMBRAL aun filtrando por etapa, y entonces no llegan al LLM.

Para ver el contexto que recibe el LLM en cada etapa, desde backend/:
    python -m app.rag.prompts --etapa 7
    python -m app.rag.prompts            # las 7 etapas del Propósito 1
"""
from __future__ import annotations

import argparse

from app.rag import guia

VERSION_PROMPT = "v4"

# Frase acordada para cuando la guía no responde. generar.py la busca al inicio
# de la respuesta para saber si el LLM rechazó la pregunta.
MENSAJE_NO_ENCONTRADA = "No encuentro esa información en la guía."
# Se agrega cuando se rechaza por el umbral, sin LLM. Ayuda sobre todo con las
# preguntas ambiguas («¿cómo se llena la ficha?»), que también quedan bajo el umbral.
SUGERENCIA = ("Prueba a reformular la pregunta con el nombre de la herramienta o de la "
              "actividad, o indica la etapa del proyecto.")

SISTEMA = f"""Eres el asistente metodológico de la plataforma SSP-UXLab. Respondes preguntas sobre la guía «¿Cómo podemos innovar en los servicios públicos desde la experiencia usuaria?» (Permitido Innovar; Laboratorio de Gobierno y Observatorio UX UTEM, 2025) usando SOLO los fragmentos de la guía que aparecen entre <contexto> y </contexto>.

Antes de escribir, decide en cuál de estos tres casos estás:

A. Los fragmentos responden la pregunta (el caso más común): responde directamente con esa información, citando cada afirmación según la regla 1. No escribas la frase del caso C.
B. La pregunta es ambigua: nombra una herramienta solo por su tipo (mapa, ficha, matriz, plan, lámina) sin decir cuál, o podría referirse a dos o más herramientas o actividades distintas, y ni la pregunta ni la etapa actual indican cuál. La guía tiene varias herramientas de cada tipo, así que es caso B aunque los fragmentos hablen de una sola. No respondas todavía: di que puede referirse a varias opciones, nombra las que aparecen en los fragmentos (con su cita) y pregunta a cuál se refiere. Si la etapa actual indica cuál es, trátala como caso A. No escribas la frase del caso C.
C. Los fragmentos no responden la pregunta: también cuando la pregunta nombra una herramienta, dato o concepto que no aparece en los fragmentos, o cuando los fragmentos tratan un tema cercano pero no responden lo que se pregunta. Empieza tu respuesta exactamente con "{MENSAJE_NO_ENCONTRADA}", sin nada antes. Después solo puedes sugerir reformular la pregunta o revisar la sección más cercana, si la hay; no expliques el contenido de otra herramienta como si fuera la pedida.

Reglas:
1. Cada fragmento empieza con una línea «fuente:». Después de cada afirmación, escribe entre corchetes el texto que sigue a «fuente:» en el fragmento que la respalda, copiado sin cambios: la sección real y todas sus páginas, también cuando es un rango. Nunca escribas una sección ni una página que no aparezca en una línea «fuente:».
2. No uses conocimientos externos. No inventes datos, cifras, fechas, plazos, nombres ni enlaces.
3. Si los fragmentos se contradicen, dilo y cita ambas partes.
4. Eres un apoyo: no tomes decisiones por el equipo. Usa un español claro y orientado a la acción, con viñetas cuando haya pasos."""

USUARIO = """Etapa actual del proyecto (si se conoce): {etapa}

<contexto>
{contexto}
</contexto>

Pregunta: {pregunta}"""

# Va a continuación de «Etapa actual del proyecto (si se conoce):». Las páginas
# quedan fuera a propósito: la regla 1 exige citar solo las líneas «fuente:» de
# los fragmentos, y una página en el contexto de la etapa invitaría a citarla.
# Unas 95 palabras por etapa (ver con --etapa), por gemma3:4b en un Mac de 8 GB.
ETAPA = """{numero} {nombre}
- Propósito {proposito}: {nombre_proposito}
- Actividad de la guía: {actividad}
- Objetivo de la etapa: {objetivo}
- {rotulo_herramientas}: {herramientas}
La etapa sirve para saber a qué herramienta o actividad se refiere la pregunta; no es un fragmento de la guía y no se cita."""


def texto_etapa(etapa: int | None, proposito: int = 1) -> str:
    """Contexto de la etapa como se le muestra al LLM; «no indicada» si no se conoce."""
    if not etapa:
        return "no indicada"
    e = guia.etapa(etapa, proposito)
    if e is None:
        return str(etapa)
    herramientas = [nombre for _, nombre in e.herramientas]
    return ETAPA.format(
        numero=e.numero, nombre=e.nombre, proposito=proposito,
        nombre_proposito=guia.PROPOSITOS[proposito].nombre, actividad=e.actividad,
        objetivo=e.objetivo, herramientas=", ".join(herramientas),
        rotulo_herramientas="Herramientas de la etapa" if len(herramientas) > 1 else "Herramienta de la etapa")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapa", type=int, help="etapa a mostrar; sin ella, todas las del propósito")
    ap.add_argument("--proposito", type=int, default=1, help="propósito de la guía (por ahora solo el 1)")
    args = ap.parse_args()

    p = guia.PROPOSITOS.get(args.proposito)
    if p is None:
        raise SystemExit(f"No hay datos del Propósito {args.proposito}. Propósitos: {sorted(guia.PROPOSITOS)}.")
    etapas = [p.etapa(args.etapa)] if args.etapa else list(p.etapas)
    if etapas == [None]:
        raise SystemExit(f"El Propósito {p.numero} no tiene etapa {args.etapa}. "
                         f"Etapas: {[e.numero for e in p.etapas]}.")
    for e in etapas:
        inicio, fin = e.paginas
        texto = texto_etapa(e.numero, p.numero)
        print(f"=== Etapa {e.numero} «{e.nombre}» · Propósito {p.numero} (p. {p.pagina})")
        print(f"actividad: {e.actividad}, págs. {inicio}-{fin}")
        print("herramientas: " + "; ".join(f"{nombre}, p. {pag}" for pag, nombre in e.herramientas))
        print("objetivo verificable en: " + ", ".join(f"p. {pag}" for pag in e.paginas_objetivo))
        print(f"\n--- Lo que recibe el LLM ({len(texto.split())} palabras) ---")
        print(f"Etapa actual del proyecto (si se conoce): {texto}\n")


if __name__ == "__main__":
    main()
