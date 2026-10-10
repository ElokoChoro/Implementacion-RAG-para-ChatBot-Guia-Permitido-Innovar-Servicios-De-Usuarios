"""
Fixtures comunes de los tests.

Los tests no cargan bge-m3, el reranker ni Ollama: reemplazan `recuperar()` y la
llamada al LLM por funciones de prueba. Así corren en segundos y en CI.

Desde la raíz del repositorio:
    .venv/bin/python -m pytest
"""
from __future__ import annotations

from pathlib import Path

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from app.rag import config

# Campos de `RespuestaGuia` en src/lib/rag.ts: el contrato de POST /ia/consultar-guia.
CAMPOS_CONTRATO = {"resultado", "encontrada", "confianza", "fuentes", "modelo", "version_prompt",
                   "modo", "puntaje", "latencia_s"}
# Campos de `Fuente` en src/types.ts: cada elemento de `fuentes`.
CAMPOS_FUENTE = {"seccion", "pagina", "fuente", "fragmento", "puntaje"}
# Campos de `AdjuntoCargado` en src/types.ts: la respuesta de POST /ia/adjuntos.
CAMPOS_ADJUNTO = {"adjunto_id", "nombre", "formato", "paginas", "fragmentos", "caracteres", "reemplazos",
                  "expira_en_s", "modo", "latencia_s"}
# Adjuntos de ejemplo, con datos ficticios (ver su README).
ADJUNTOS = Path(__file__).resolve().parent / "datos" / "adjuntos"


@pytest.fixture(autouse=True)
def umbrales(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija el umbral y los cortes de confianza: el .env de quien corre los tests no debe cambiarlos."""
    monkeypatch.setattr(config, "UMBRAL", 0.5)
    monkeypatch.setattr(config, "CONFIANZA_MEDIA", 0.7)
    monkeypatch.setattr(config, "CONFIANZA_ALTA", 0.9)


def fragmento(puntaje: float, texto: str = "El plano del servicio muestra…", **metadatos) -> NodeWithScore:
    """Fragmento de la guía con los metadatos que deja la ingesta y el puntaje del reranker."""
    meta = {
        "seccion": "Herramientas",
        "actividad": "Momentos críticos",
        "herramienta": "Plano del servicio",
        "pagina_inicio": 120,
        "fuente": "Herramientas › Plano del servicio, p. 120",
        **metadatos,
    }
    return NodeWithScore(node=TextNode(text=texto, metadata=meta), score=puntaje)
