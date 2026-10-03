"""
Estructura de la guía y etapas de la plataforma SSP-UXLab, como datos.

La comparten la ingesta (ingesta/corpus.py etiqueta cada página con su
sección, actividad, herramienta y etapa) y la consulta (prompts.py le da al
LLM el contexto de la etapa desde la que se pregunta). Así hay una sola fuente
de verdad para las etapas.

Cada propósito de la guía es una secuencia de etapas, y cada etapa se apoya en
una actividad de la guía. Las páginas y las herramientas de la etapa se deducen
de las tablas ACTIVIDADES y HERRAMIENTAS; a mano solo van el nombre de la etapa
en la plataforma, la actividad y el objetivo, que sale de la propia guía (con
la página donde se puede verificar). El nombre, la actividad y el objetivo de
cada etapa, y los nombres de las herramientas, llegan al LLM
(prompts.texto_etapa): cambiarlos cambia el prompt y obliga a subir
VERSION_PROMPT en prompts.py.

Los datos de otro propósito se agregan a PROPOSITOS sin cambiar este módulo,
pero hoy la consulta usa solo el Propósito 1: para que un propósito nuevo llegue
al LLM hay que pasarlo por responder() y _generar (generar.py) y por el contrato
de POST /ia/consultar-guia (api.py). El corpus sigue etiquetado con las etapas
del Propósito 1 (ver ETAPAS).

Para ver el contexto que recibe el LLM en una etapa, desde backend/:
    python -m app.rag.prompts --etapa 7
"""
from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Estructura de la guía, tomada de sus índices (págs. 4 a 6).
# Cada tupla es (página donde empieza, nombre). Si cambia la guía, hay que
# revisar estas tablas y volver a generar el corpus (python -m ingesta.corpus).
# --------------------------------------------------------------------------
SECCIONES = [
    (1, "Créditos de la guía"),
    (8, "Prólogos"),
    (10, "Innovación pública y democracia"),
    (13, "Introducción"),
    (23, "Lo primero: actividades base para la gestión de la experiencia usuaria"),
    (27, "Propósitos"),
    (28, "Propósito 1: Comprender la experiencia actual de las personas usuarias"),
    (32, "Propósito 2: Incorporar perspectiva usuaria al quehacer institucional"),
    (36, "Propósito 3: Mejorar la satisfacción con un servicio"),
    (40, "Propósito 4: Mejorar la colaboración interna para la experiencia usuaria"),
    (44, "Propósito 5: Diseñar e implementar un nuevo servicio"),
    (51, "Actividades y herramientas"),
    (158, "Glosario"),
    (162, "¿Cómo elaboramos esta guía?"),
    (164, "Referencias"),
]

ACTIVIDADES = [
    (54, "Actores"), (58, "Adopción"), (64, "Claves perceptuales"),
    (68, "Competencias"), (72, "Comunicación"), (76, "Contexto institucional"),
    (80, "Creación de valor"), (86, "Ecosistema de canales"), (90, "Estándares"),
    (94, "Experiencia modelo"), (100, "Habilitación y Expectativas"),
    (104, "Interacciones"), (108, "Investigación"), (112, "Marco Institucional"),
    (116, "Medición"), (120, "Modelo operativo"), (126, "Momentos críticos"),
    (132, "Necesidades"), (140, "Personas"), (150, "Sensibilización"),
    (154, "Vinculación"),
]
FIN_ACTIVIDADES = 158  # el Glosario: la última actividad (Vinculación) termina en la p. 157

HERRAMIENTAS = sorted([
    (152, "Ficha de actividades de sensibilización"),
    (88, "Ficha de caracterización de canales"),
    (114, "Ficha de caracterización institucional"),
    (70, "Ficha de competencias para la experiencia"),
    (78, "Ficha de contexto institucional"),
    (92, "Ficha de estándares de servicio"),
    (60, "Ficha de intervenciones para la adopción"),
    (66, "Lista de claves perceptuales"),
    (56, "Mapa de actores del ecosistema del servicio"),
    (82, "Mapa de co-producción valor"),
    (102, "Mapa de expectativas"),
    (128, "Mapa de momentos críticos"),
    (142, "Mapa de perfiles de personas usuarias"),
    (134, "Mapa del problema completo"),
    (156, "Matriz de vinculación entre necesidades y servicios"),
    (148, "Perfil de persona usuaria"),
    (136, "Pilares del servicio"),
    (74, "Plan de comunicaciones del servicio"),
    (118, "Plan de evaluación de estándares de servicio"),
    (110, "Plan de investigación de experiencia usuaria"),
    (122, "Plano del servicio"),
    (106, "Viaje de la persona usuaria"),
    (96, "Viaje ideal de la persona usuaria"),
])


def paginas_actividad(actividad: str) -> tuple[int, int]:
    """Primera y última página de una actividad, según ACTIVIDADES."""
    inicios = [inicio for inicio, _ in ACTIVIDADES] + [FIN_ACTIVIDADES]
    i = next((i for i, (_, nombre) in enumerate(ACTIVIDADES) if nombre == actividad), None)
    if i is None:
        raise ValueError(f"«{actividad}» no está en ACTIVIDADES.")
    return inicios[i], inicios[i + 1] - 1


def herramientas_actividad(actividad: str) -> list[tuple[int, str]]:
    """Herramientas (página, nombre) que empiezan dentro de una actividad."""
    inicio, fin = paginas_actividad(actividad)
    return [(p, nombre) for p, nombre in HERRAMIENTAS if inicio <= p <= fin]


# --------------------------------------------------------------------------
# Propósitos y etapas de la plataforma
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Etapa:
    numero: int
    nombre: str              # como aparece en la plataforma
    actividad: str           # actividad de la guía que la respalda, tal como está en ACTIVIDADES
    objetivo: str            # de la guía, con sus palabras
    paginas_objetivo: tuple[int, ...]  # páginas donde se verifica el objetivo

    @property
    def paginas(self) -> tuple[int, int]:
        return paginas_actividad(self.actividad)

    @property
    def herramientas(self) -> list[tuple[int, str]]:
        return herramientas_actividad(self.actividad)


@dataclass(frozen=True)
class Proposito:
    numero: int
    nombre: str
    pagina: int              # donde empieza en la guía (SECCIONES)
    etapas: tuple[Etapa, ...]

    def etapa(self, numero: int) -> Etapa | None:
        return next((e for e in self.etapas if e.numero == numero), None)


# El objetivo de cada etapa une la línea de la actividad en la lista del
# Propósito 1 (p. 30) con «¿En qué consiste?» de la propia actividad.
PROPOSITOS = {
    1: Proposito(1, "Comprender la experiencia actual de las personas usuarias", 28, (
        Etapa(1, "Investigación", "Investigación",
              "Diseñar y ejecutar la investigación de las personas usuarias, para comprender mejor "
              "sus vivencias, necesidades y expectativas, su relación con el servicio y los recursos "
              "con que cuentan para acceder a él y usarlo.",
              (30, 108)),
        Etapa(2, "Personas usuarias", "Personas",
              "Describir a las personas usuarias de los servicios institucionales: trabajar con "
              "perfiles diferenciados, basados en evidencia, que reflejen la diversidad de sus "
              "necesidades, expectativas, comportamientos, motivaciones y condiciones de vida.",
              (30, 140)),
        Etapa(3, "Habilitación y expectativas", "Habilitación y Expectativas",
              "Detectar y consensuar los niveles de habilitación y expectativas de las personas "
              "usuarias para el servicio: lo que esperan de él antes de acceder y los recursos con "
              "que cuentan para utilizarlo.",
              (30, 100)),
        Etapa(4, "Necesidades", "Necesidades",
              "Comprender a fondo las motivaciones y necesidades de las personas al recurrir al "
              "servicio: los motivos que las impulsan a interactuar con él, más allá de los trámites "
              "u objetivos explícitos. El principal insumo son los resultados de la Investigación.",
              (30, 132)),
        Etapa(5, "Vinculación", "Vinculación",
              "Alinear las necesidades de las personas usuarias con la oferta de servicio: analizar "
              "en qué medida los servicios responden a sus necesidades, objetivos y expectativas, e "
              "identificar coincidencias, vacíos, duplicidades o desajustes.",
              (30, 154)),
        Etapa(6, "Medición", "Medición",
              "Observar y medir la experiencia real entregada a través de los estándares de servicio "
              "disponibles, para determinar si los niveles de calidad, atención y respuesta "
              "declarados como deseables ocurren en la práctica.",
              (30, 116)),
        Etapa(7, "Momentos críticos", "Momentos críticos",
              "Identificar los momentos críticos de la experiencia actual: los momentos del "
              "recorrido de una persona usuaria donde se concentra la mayor fricción, frustración o "
              "riesgo de abandono, para priorizar mejoras donde el impacto es más significativo.",
              (30, 126)),
    )),
}

# Una actividad mal escrita dejaría la etapa sin páginas ni herramientas (y sin
# etiquetar en el corpus): mejor fallar al importar.
for _p in PROPOSITOS.values():
    for _e in _p.etapas:
        if _e.actividad not in {nombre for _, nombre in ACTIVIDADES}:
            raise ValueError(f"Propósito {_p.numero}, etapa {_e.numero}: «{_e.actividad}» "
                             "no está en ACTIVIDADES.")

# Etapa (1 a 7) -> actividad, para etiquetar el corpus. Son las etapas del
# Propósito 1, el que usa hoy la plataforma: si se suman otros propósitos, el
# corpus sigue etiquetado con estas, porque cambiar estos valores cambiaría
# data/corpus/v2 y obligaría a una versión nueva del corpus.
ETAPAS = {e.numero: e.actividad for e in PROPOSITOS[1].etapas}


def etapa(numero: int, proposito: int = 1) -> Etapa | None:
    """Etapa `numero` del propósito indicado; None si no existe."""
    p = PROPOSITOS.get(proposito)
    return p.etapa(numero) if p else None
