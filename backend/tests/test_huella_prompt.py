"""
Huella de los mensajes que recibe el LLM: si cambian, tiene que cambiar la versión del prompt.

Los resultados de eval/ se comparan por VERSION_PROMPT, VERSION_PROMPT_ETAPA y
VERSION_PROMPT_REVISION. Un cambio en el texto de los prompts, en los datos de guia.py que
llegan al LLM (nombre, actividad y objetivo de cada etapa, nombres de herramientas), en los
textos de una rúbrica que lee el LLM o en cómo se arma el contexto cambia lo que lee el
modelo: este test falla hasta que subas la versión, la anotes en el docstring de prompts.py,
prompts_etapa.py o app/revision/prompts.py y agregues aquí la huella nueva.

Un refactor que no cambia el texto deja la huella igual.
"""
from __future__ import annotations

import hashlib

import pytest
from llama_index.core.llms import ChatMessage
from llama_index.core.schema import NodeWithScore, TextNode

from app.rag import generar, guia, sugerir
from app.rag.flujo import Tokens
from app.rag.prompts import VERSION_PROMPT
from app.rag.prompts_etapa import VERSION_PROMPT_ETAPA
from app.revision import revisar, rubricas
from app.revision.prompts import VERSION_PROMPT_REVISION

# Huella de cada versión vigente. Al subir una versión, agrega la suya (las anteriores pueden quedar).
HUELLAS = {
    "v4": "a1598306054b0dae",
    "etapa-v1": "ded65b79d333ceb5",
    "revision-v1": "756826ccf2bbdb39",
}
ETAPAS = [e.numero for e in guia.PROPOSITOS[1].etapas]


def _nodo(texto: str, fuente: str, puntaje: float) -> NodeWithScore:
    """Fragmento como los de la ingesta: al LLM solo le llega la línea «fuente»."""
    meta = {"fuente": fuente, "seccion": "Actividades y herramientas", "pagina_inicio": 122}
    return NodeWithScore(node=TextNode(text=texto, metadata=meta, excluded_llm_metadata_keys=["seccion",
                                                                                              "pagina_inicio"]),
                         score=puntaje)


NODOS = [_nodo("## PLANO DEL SERVICIO\n\nEsta herramienta…", "Modelo operativo › Plano del servicio, p. 122", 0.93),
         _nodo("## ¿CUÁNDO DESARROLLARLA?\n\nAl inicio…", "Investigación, p. 109", 0.71)]


def _huella(mensajes: list[list[ChatMessage]]) -> str:
    texto = "\n=====\n".join(f"{m.role.value}\n{m.content}" for lista in mensajes for m in lista)
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


def test_prompt_de_preguntas(monkeypatch: pytest.MonkeyPatch) -> None:
    enviados: list[list[ChatMessage]] = []
    monkeypatch.setattr(generar, "chat", lambda mensajes: enviados.append(mensajes) or ("", Tokens()))
    for etapa in [None, *ETAPAS]:
        generar._generar("¿Qué es un plano del servicio?", etapa, NODOS)

    assert _huella(enviados) == HUELLAS.get(VERSION_PROMPT), (
        f"Cambiaron los mensajes de prompts.py (huella {_huella(enviados)}): sube VERSION_PROMPT, anótalo en "
        "el docstring de prompts.py y agrega la huella a HUELLAS.")


def test_prompt_por_etapa() -> None:
    proyectos = [sugerir.texto_proyecto(None, None),
                 sugerir.texto_proyecto("Licencias médicas <b>", {"mapa_momentos_criticos": "pendiente"})]
    enviados = [sugerir.mensajes(etapa, NODOS, proyecto) for etapa in ETAPAS for proyecto in proyectos]

    assert _huella(enviados) == HUELLAS.get(VERSION_PROMPT_ETAPA), (
        f"Cambiaron los mensajes de prompts_etapa.py (huella {_huella(enviados)}): sube VERSION_PROMPT_ETAPA, "
        "anótalo en su docstring y agrega la huella a HUELLAS.")


def test_prompt_de_revision() -> None:
    documento = "Perfil: Rosa <b>\n\nRol: conductora, RUT [RUT_1].\n\nNecesidades: saber qué llevar."
    enviados = []
    for herramienta in rubricas.disponibles():
        r = rubricas.cargar(herramienta)
        enviados.append(revisar.mensajes_resumen(r, documento))
        enviados += [revisar.mensajes_criterio(r, c, documento) for c in r.criterios]

    assert _huella(enviados) == HUELLAS.get(VERSION_PROMPT_REVISION), (
        f"Cambiaron los mensajes de la revisión (huella {_huella(enviados)}): sube VERSION_PROMPT_REVISION, "
        "anótalo en el docstring de app/revision/prompts.py y agrega la huella a HUELLAS.")
