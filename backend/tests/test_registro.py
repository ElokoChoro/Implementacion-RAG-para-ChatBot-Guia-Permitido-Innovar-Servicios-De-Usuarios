"""Formato de las líneas del log (registro.py) y que no guardan el texto que escribe la persona."""
from __future__ import annotations

import logging

import pytest
from conftest import fragmento

from app.rag import generar, registro, sugerir

PREGUNTA = "¿Mi RUT 12.345.678-9 sirve para el trámite?"


def test_campos() -> None:
    assert registro.campos(estado=503, motivo="cola_llena", mejor=0.93612, encontrada=False, confianza=None,
                           espera_s=2.0, detalle="Inicia Ollama.") == \
        'estado=503 motivo=cola_llena mejor=0.936 encontrada=false confianza=- espera_s=2 detalle="Inicia Ollama."'


def test_pregunta_con_tiempos_y_sin_su_texto(monkeypatch: pytest.MonkeyPatch,
                                             caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: [fragmento(0.93), fragmento(0.2)])
    monkeypatch.setattr(generar, "_generar", lambda *a: "Respuesta [fuente].")

    with caplog.at_level(logging.INFO, logger="app.rag.generar"):
        generar.responder(PREGUNTA, 7)

    linea = caplog.records[-1].getMessage()
    for campo in ("etapa=7", "filtrar_etapa=false", f"largo_pregunta={len(PREGUNTA)}", "mejor=0.93",
                  "fragmentos=1", "t_recuperacion_s=", "t_llm_s=", "encontrada=true"):
        assert campo in linea
    assert "RUT" not in caplog.text


def test_pregunta_bajo_el_umbral(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: [fragmento(0.3)])

    with caplog.at_level(logging.INFO, logger="app.rag.generar"):
        generar.responder(PREGUNTA)

    linea = caplog.records[-1].getMessage()
    assert "mejor=0.3 " in linea and "llm=no" in linea and "t_llm_s" not in linea


def test_sugerir_sin_el_texto_del_proyecto(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(sugerir, "recuperar", lambda *a, **k: [fragmento(0.95)])
    monkeypatch.setattr(sugerir, "chat", lambda m: "Pasos.")

    with caplog.at_level(logging.INFO, logger="app.rag.sugerir"):
        sugerir.sugerir(4, "Licencias médicas de Juana Pérez")

    linea = caplog.records[-1].getMessage()
    assert "etapa=4" in linea and "largo_proyecto=" in linea and "t_llm_s=" in linea
    assert "Juana" not in caplog.text


def test_sugerir_sin_proyecto(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(sugerir, "recuperar", lambda *a, **k: [fragmento(0.95)])
    monkeypatch.setattr(sugerir, "chat", lambda m: "Pasos.")

    with caplog.at_level(logging.INFO, logger="app.rag.sugerir"):
        sugerir.sugerir(4)

    assert "largo_proyecto=0 " in caplog.records[-1].getMessage()
