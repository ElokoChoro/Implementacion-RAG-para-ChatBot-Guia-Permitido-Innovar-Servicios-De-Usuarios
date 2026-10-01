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
  v3  (vigente) v2 sin la regla de terminar con la certeza: la confianza la
      calcula el backend con el puntaje del reranker (ver generar.py).
"""
from __future__ import annotations

VERSION_PROMPT = "v3"

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

# Etapas de la plataforma SSP-UXLab y la actividad de la guía que les corresponde
ETAPAS = {
    1: "1 Investigación", 2: "2 Personas usuarias", 3: "3 Habilitación y expectativas",
    4: "4 Necesidades", 5: "5 Vinculación", 6: "6 Medición", 7: "7 Momentos críticos",
}


def texto_etapa(etapa: int | None) -> str:
    """Etapa como se le muestra al LLM; «no indicada» si no se conoce."""
    if not etapa:
        return "no indicada"
    return ETAPAS.get(etapa, str(etapa))
