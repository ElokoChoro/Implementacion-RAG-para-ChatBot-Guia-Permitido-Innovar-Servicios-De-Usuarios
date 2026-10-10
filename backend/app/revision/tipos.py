"""
Forma de la respuesta de POST /ia/revisar-entregable y el texto que se le muestra a la persona.

No importa LlamaIndex ni modelos: lo usa también el simulador. Como en
contrato.Respuesta, un campo nuevo solo se agrega, con valor por defecto, para
no romper a quien ya consume la API.

Estados de cada criterio:
  cumple        el documento incluye lo que pide la guía (✅)
  parcial       incluye una parte (⚠️)
  no_cumple     no aparece (❌)
  no_evaluable  no se pudo revisar: el LLM no respondió un JSON válido o citó un
                texto que no está en el documento (❔). Se le pide a la persona
                que lo revise ella.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Estado = Literal["cumple", "parcial", "no_cumple", "no_evaluable"]
ESTADOS: tuple[str, ...] = ("cumple", "parcial", "no_cumple", "no_evaluable")
ICONOS = {"cumple": "✅", "parcial": "⚠️", "no_cumple": "❌", "no_evaluable": "❔"}
NO_EVALUABLE = "No pude confirmarlo en el documento: revísalo tú."
AVISO = ("Esta revisión solo comprueba que el documento tenga lo que pide la guía; no evalúa si el "
         "contenido es bueno. Es una sugerencia: revísala antes de usarla.")


@dataclass
class CriterioRevisado:
    """Un punto de la rúbrica, revisado."""

    id: str
    nombre: str
    tipo: Literal["obligatorio", "recomendado"]
    estado: Estado
    evidencia: str        # texto del documento que lo respalda; vacío si no cumple
    sugerencia: str       # qué falta y qué agregar; vacío si cumple
    pagina: int           # página de la guía que lo pide
    cita: str             # «p. 148, paso 3»
    revisado_con: Literal["llm", "codigo"]


@dataclass
class Revision:
    """Respuesta de POST /ia/revisar-entregable."""

    herramienta: str                  # id de la rúbrica
    nombre: str                       # nombre de la herramienta en la guía
    fuente: str                       # «Personas › Perfil de persona usuaria, p. 148»
    version_rubrica: str
    rubrica_validada: bool            # false mientras UXLab no apruebe la rúbrica
    resumen: str                      # 2 o 3 frases sobre lo cargado, sin juicio de calidad
    criterios: list[CriterioRevisado]
    obligatorios: int                 # cuántos criterios obligatorios tiene la rúbrica
    obligatorios_cumplidos: int
    resultado: str                    # resumen y checklist en markdown, listo para el chat
    modelo: str = ""
    version_prompt: str = ""
    modo: str = "local"               # «local» (modelos) o «simulador» (respuesta fija)
    latencia_s: float = 0.0
    tokens_prompt: int | None = None  # suma de las llamadas al LLM; None si el servidor no los informa
    tokens_respuesta: int | None = None
    llamadas_llm: int = 0

    def a_dict(self) -> dict:
        return asdict(self)


def _linea(c: CriterioRevisado) -> str:
    if c.estado == "cumple":
        return f"{ICONOS['cumple']} {c.nombre}"
    return f"{ICONOS[c.estado]} **{c.nombre}**: {c.sugerencia} Ver {c.cita}."


def texto_revision(nombre: str, fuente: str, resumen: str, criterios: list[CriterioRevisado]) -> str:
    """
    La revisión en markdown, como se le muestra a la persona en el chat.

    Los obligatorios van todos, con su estado; de los recomendados solo los que
    faltan o están incompletos, como sugerencias.
    """
    obligatorios = [_linea(c) for c in criterios if c.tipo == "obligatorio"]
    sugerencias = [f"- {c.sugerencia} Ver {c.cita}." for c in criterios
                   if c.tipo == "recomendado" and c.estado in ("parcial", "no_cumple")]
    partes = [f"**Resumen:** {resumen}", f"**Lo que pide la guía para el {nombre}** ({fuente}):\n\n"
              + "\n".join(obligatorios)]
    if sugerencias:
        partes.append("**Sugerencias:**\n" + "\n".join(sugerencias))
    partes.append(f"_{AVISO}_")
    return "\n\n".join(partes)
