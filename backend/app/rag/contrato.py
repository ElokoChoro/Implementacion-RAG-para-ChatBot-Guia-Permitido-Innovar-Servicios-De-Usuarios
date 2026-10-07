"""
Forma de la respuesta de la API (`POST /ia/consultar-guia` y `POST /ia/sugerir-proximos-pasos`),
acordada con la plataforma.

Va en un módulo aparte, sin LlamaIndex ni modelos, para que la usen igual
generar.py (respuestas reales), sugerir.py (asistente por etapa) y simulador.py
(respuestas fijas para integrar la plataforma sin modelos). Así las tres
devuelven siempre los mismos campos.

No cambies los campos sin acordarlo: los tests los comparan con `RespuestaGuia`
de src/lib/rag.ts y `Fuente` de src/types.ts (CAMPOS_CONTRATO y CAMPOS_FUENTE en
tests/conftest.py). Un campo nuevo solo puede agregarse, y con valor por defecto,
para no romper a quien ya consume la API. `Fuente` y la confianza están tipadas
para que /openapi.json las documente; el JSON es el mismo.

Para ver los campos y un ejemplo, desde backend/:
    python -m app.rag.contrato
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from typing import Literal, TypedDict

from app.rag import config
from app.rag.prompts import VERSION_PROMPT


class Fuente(TypedDict):
    """
    Un fragmento de la guía que respalda la respuesta.

    Es un diccionario: tiparlo no cambia el JSON, pero así /openapi.json
    documenta sus campos para quien integra la API.
    """

    seccion: str      # herramienta, actividad o sección del fragmento (la más específica)
    pagina: int       # página donde empieza
    fuente: str       # «Sección › Herramienta, p. N», como lo cita la respuesta
    fragmento: str    # primeros 300 caracteres del fragmento
    puntaje: float    # puntaje del reranker, de 0 a 1


@dataclass
class Respuesta:
    """Respuesta con la forma del contrato de los dos POST de la API."""

    resultado: str
    encontrada: bool
    confianza: Literal["alta", "media", "baja"] | None  # None si no se encontró
    fuentes: list[Fuente] = field(default_factory=list)
    modelo: str = config.LLM
    version_prompt: str = VERSION_PROMPT
    modo: str = "local"            # «local» (modelos) o «simulador» (respuestas fijas)
    puntaje: float | None = None   # mejor puntaje del reranker, para auditar el umbral
    latencia_s: float = 0.0

    def a_dict(self) -> dict:
        return asdict(self)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    ejemplo = Respuesta(resultado="Texto de la respuesta, con sus citas.", encontrada=True, confianza="alta",
                        fuentes=[{"seccion": "Plano del servicio", "pagina": 120,
                                  "fuente": "Actividades y herramientas › Plano del servicio, p. 120",
                                  "fragmento": "Texto del fragmento usado…", "puntaje": 0.93}],
                        puntaje=0.93, latencia_s=12.3)
    print(json.dumps(ejemplo.a_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
