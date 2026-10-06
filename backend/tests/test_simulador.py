"""
Simulador (MODO=simulador): forma del contrato, marcas de cada caso y que corre sin modelos,
en las preguntas (responder) y en los próximos pasos de cada etapa (sugerir).

La plataforma integra la API contra el simulador, así que debe responder lo mismo
que generar.py en forma, validación y errores.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import CAMPOS_CONTRATO
from fastapi.testclient import TestClient

from app import api
from app.rag import config, guia, simulador
from app.rag.prompts import MENSAJE_NO_ENCONTRADA, SUGERENCIA
from app.rag.prompts_etapa import VERSION_PROMPT_ETAPA

BACKEND = Path(__file__).resolve().parents[1]
CORPUS = BACKEND.parent / "data" / "corpus" / "v3" / "paginas.jsonl"
ETAPAS = [e.numero for e in guia.PROPOSITOS[1].etapas]


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """La API con el simulador en vez de generar.py, como con MODO=simulador."""
    monkeypatch.setattr(api, "responder", simulador.responder)
    monkeypatch.setattr(api, "sugerir", simulador.sugerir)
    monkeypatch.setattr(api, "_clave_servicio", lambda: "")
    return TestClient(api.app)


def test_respuesta_por_defecto() -> None:
    r = simulador.responder("¿Qué es un plano del servicio?")

    assert set(r.a_dict()) == CAMPOS_CONTRATO
    assert r.encontrada is True
    assert r.confianza == "alta"
    assert r.modo == r.modelo == "simulador"


@pytest.mark.parametrize("etapa", sorted(simulador.RESPUESTAS))
def test_las_citas_estan_en_las_fuentes(etapa: int) -> None:
    r = simulador.responder("¿Qué es?", etapa)
    citas = set(re.findall(r"\[([^\]]+)\]", r.resultado))

    assert citas and citas <= {f["fuente"] for f in r.fuentes}


@pytest.mark.parametrize("marca, confianza, puntaje", [
    ("", "alta", 0.95), ("#confianza-media", "media", 0.8), ("#CONFIANZA-BAJA", "baja", 0.6),
])
def test_confianza_segun_la_marca(marca: str, confianza: str, puntaje: float) -> None:
    r = simulador.responder(f"¿Qué es? {marca}")

    assert r.confianza == confianza
    assert r.puntaje == puntaje
    assert config.UMBRAL <= r.puntaje
    assert all(f["puntaje"] <= r.puntaje for f in r.fuentes)


def test_no_encontrada() -> None:
    r = simulador.responder("¿Cuánto presupuesto se necesita? #no-encontrada")

    assert r.encontrada is False
    assert r.resultado == f"{MENSAJE_NO_ENCONTRADA} {SUGERENCIA}"
    assert r.confianza is None
    assert r.fuentes == []
    assert r.puntaje < config.UMBRAL


@pytest.mark.parametrize("etapa, pagina", [(1, 110), (2, 142), (7, 122), (None, 122), (4, 122)])
def test_la_etapa_elige_la_respuesta(etapa: int | None, pagina: int) -> None:
    r = simulador.responder("¿Qué es?", etapa)

    assert f"p. {pagina}]" in r.resultado


def test_api_con_el_simulador(cliente: TestClient) -> None:
    r = cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué herramienta sirve para investigar?", "etapa": 1})

    assert r.status_code == 200
    assert set(r.json()) == CAMPOS_CONTRATO
    assert r.json()["modo"] == "simulador"


def test_api_error_con_el_simulador(cliente: TestClient) -> None:
    r = cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué es? #error"})

    assert r.status_code == 503
    assert r.json()["detail"].startswith("Simulador:")


def test_api_valida_igual_con_el_simulador(cliente: TestClient) -> None:
    assert cliente.post("/ia/consultar-guia", json={"pregunta": "x" * 1001}).status_code == 422


@pytest.mark.parametrize("etapa", ETAPAS)
def test_sugerir_cada_etapa(etapa: int) -> None:
    r = simulador.sugerir(etapa)
    citas = {c.strip() for grupo in re.findall(r"\[([^\]]+)\]", r.resultado) for c in grupo.split(";")}

    assert set(r.a_dict()) == CAMPOS_CONTRATO
    assert r.encontrada is True and r.confianza == "alta"
    assert r.version_prompt == VERSION_PROMPT_ETAPA
    assert r.modo == r.modelo == "simulador"
    # El formato de prompts_etapa.py, de tres a cinco pasos.
    assert r.resultado.startswith("**Qué busca esta etapa:**")
    assert "**Herramienta sugerida:**" in r.resultado
    assert 3 <= r.resultado.count("\n- ") <= 5
    assert citas and citas <= {f["fuente"] for f in r.fuentes}


def test_sugerir_cita_como_el_corpus() -> None:
    # Las citas del simulador tienen que existir tal cual en las líneas «fuente:» del corpus,
    # para que la plataforma pruebe con citas reales.
    del_corpus = {json.loads(linea)["fuente"] for linea in CORPUS.open(encoding="utf-8")}
    del_simulador = {f["fuente"] for etapa in ETAPAS for f in simulador.sugerir(etapa).fuentes}

    assert del_simulador <= del_corpus


@pytest.mark.parametrize("contexto, datos_etapa, confianza", [
    ("Licencias médicas #confianza-media", None, "media"),
    (None, {"nota": "#CONFIANZA-BAJA"}, "baja"),
    ({"#confianza-media": True}, None, "media"),
])
def test_sugerir_marcas(contexto, datos_etapa, confianza: str) -> None:
    r = simulador.sugerir(7, contexto, datos_etapa)

    assert r.confianza == confianza
    assert r.puntaje == simulador.PUNTAJES[confianza]
    assert all(f["puntaje"] <= r.puntaje for f in r.fuentes)


def test_sugerir_no_encontrada() -> None:
    r = simulador.sugerir(3, "Proyecto #no-encontrada")

    assert r.encontrada is False
    assert r.resultado.startswith(MENSAJE_NO_ENCONTRADA)
    assert r.confianza is None and r.fuentes == []
    assert r.version_prompt == VERSION_PROMPT_ETAPA


@pytest.mark.parametrize("etapa", [0, 8])
def test_sugerir_etapa_inexistente(etapa: int) -> None:
    with pytest.raises(ValueError):
        simulador.sugerir(etapa)


def test_api_sugerir_con_el_simulador(cliente: TestClient) -> None:
    ok = cliente.post("/ia/sugerir-proximos-pasos", json={"etapa": 5, "datos_etapa": {"matriz": "pendiente"}})
    error = cliente.post("/ia/sugerir-proximos-pasos", json={"etapa": 5, "contexto": "#error"})

    assert ok.status_code == 200
    assert set(ok.json()) == CAMPOS_CONTRATO
    assert ok.json()["modo"] == "simulador"
    assert error.status_code == 503
    assert error.json()["detail"].startswith("Simulador:")


def test_modo_simulador_no_importa_los_modelos() -> None:
    # En un proceso aparte: aquí conftest ya importó LlamaIndex. Con MODO=simulador la API
    # tiene que correr solo con backend/requirements-simulador.txt.
    codigo = ("import sys, app.api; "
              "pesados = sorted({m.split('.')[0] for m in sys.modules} & "
              "{'llama_index', 'FlagEmbedding', 'torch', 'ollama', 'openai', 'chromadb'}); "
              "print(app.api.responder.__module__, app.api.sugerir.__module__, pesados)")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=BACKEND, capture_output=True, text=True,
                            env={**os.environ, "MODO": "simulador"}, check=True).stdout

    assert salida.strip() == "app.rag.simulador app.rag.simulador []"
