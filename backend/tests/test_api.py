"""Validación y códigos de error de la API HTTP, con `responder()` reemplazado."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import api
from app.rag.generar import Respuesta

cliente = TestClient(api.app)


@pytest.fixture
def llamadas(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Reemplaza `responder()` y anota con qué argumentos se llamó."""
    registro: list[tuple] = []

    def responder(pregunta, etapa=None, filtrar_etapa=False):
        registro.append((pregunta, etapa, filtrar_etapa))
        return Respuesta(resultado="Respuesta.", encontrada=True, confianza="alta", puntaje=0.93)

    monkeypatch.setattr(api, "responder", responder)
    return registro


def test_consulta(llamadas: list[tuple]) -> None:
    r = cliente.post("/ia/consultar-guia", json={"pregunta": "  ¿Qué es un plano del servicio?  ", "etapa": 7})

    assert r.status_code == 200
    assert r.json()["resultado"] == "Respuesta."
    assert r.json()["confianza"] == "alta"
    assert llamadas == [("¿Qué es un plano del servicio?", 7, False)]  # sin espacios sobrantes


@pytest.mark.parametrize("cuerpo", [
    {"pregunta": ""},
    {"pregunta": "   "},
    {"pregunta": "x" * 1001},
    {"pregunta": "¿Qué es?", "etapa": 0},
    {"pregunta": "¿Qué es?", "etapa": 8},
    {},
])
def test_consulta_invalida(llamadas: list[tuple], cuerpo: dict) -> None:
    r = cliente.post("/ia/consultar-guia", json=cuerpo)

    assert r.status_code == 422
    assert llamadas == []


def test_llm_no_disponible(monkeypatch: pytest.MonkeyPatch) -> None:
    def responder(*_args):
        raise RuntimeError("El modelo local no está disponible. Inicia Ollama (ollama serve).")

    monkeypatch.setattr(api, "responder", responder)
    r = cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué es?"})

    assert r.status_code == 503
    assert r.json()["detail"] == "El modelo local no está disponible. Inicia Ollama (ollama serve)."


def test_salud() -> None:
    r = cliente.get("/salud")

    assert r.status_code == 200
    assert set(r.json()) == {"almacen", "proveedor_llm", "llm_url", "llm", "embeddings", "reranker", "umbral"}
