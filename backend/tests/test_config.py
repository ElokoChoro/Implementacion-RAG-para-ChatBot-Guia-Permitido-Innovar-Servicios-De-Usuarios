"""Lectura de variables de entorno y nombre de la colección de Chroma."""
from __future__ import annotations

import pytest

from app.rag import config


def test_env_usa_el_defecto_si_falta_o_esta_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRUEBA_RAG", raising=False)
    assert config._env("PRUEBA_RAG", 4, int) == 4
    monkeypatch.setenv("PRUEBA_RAG", "")
    assert config._env("PRUEBA_RAG", 4, int) == 4


def test_env_convierte_al_tipo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEBA_RAG", "6")
    assert config._env("PRUEBA_RAG", 4, int) == 6
    monkeypatch.setenv("PRUEBA_RAG", "0.35")
    assert config._env("PRUEBA_RAG", 0.5, float) == 0.35


@pytest.mark.parametrize("valor, esperado", [
    ("true", True), ("1", True), ("sí", True), ("si", True), (" TRUE ", True),
    ("false", False), ("0", False), ("no", False),
])
def test_env_booleanos(monkeypatch: pytest.MonkeyPatch, valor: str, esperado: bool) -> None:
    monkeypatch.setenv("PRUEBA_RAG", valor)
    assert config._env("PRUEBA_RAG", not esperado, bool) is esperado


def test_coleccion_incluye_corpus_modelo_y_fragmentacion(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cada combinación tiene su colección: así dos configuraciones no mezclan vectores.
    monkeypatch.setattr(config, "VERSION_CORPUS", "v2")
    monkeypatch.setattr(config, "EMBEDDINGS", "BAAI/bge-m3")
    monkeypatch.setattr(config, "CHUNK_TOKENS", 400)
    monkeypatch.setattr(config, "CHUNK_OVERLAP", 50)
    assert config.coleccion() == "guia_v2_bge-m3_c400o50"


def test_llm_api_key_del_entorno_del_llavero_o_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    # El entorno manda; si no está, el llavero; y si no está en ninguno, cualquier texto
    # (los servidores locales no la piden, pero el cliente de OpenAI exige una).
    llavero: dict[str, str] = {}
    monkeypatch.setattr(config.secretos, "leer", llavero.get)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert config.llm_api_key() == "sin-clave"
    llavero["LLM_API_KEY"] = "del-llavero"
    assert config.llm_api_key() == "del-llavero"
    monkeypatch.setenv("LLM_API_KEY", "del-entorno")
    assert config.llm_api_key() == "del-entorno"
