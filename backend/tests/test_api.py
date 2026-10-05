"""Validación, clave, turno y códigos de error de la API HTTP, con `responder()` y `sugerir()` reemplazados."""
from __future__ import annotations

import inspect
import logging
import threading

import pytest
from conftest import CAMPOS_CONTRATO
from fastapi.testclient import TestClient

from app import api
from app.rag import config
from app.rag.contrato import Respuesta

cliente = TestClient(api.app)


@pytest.fixture(autouse=True)
def sin_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin CLAVE_SERVICIO, como en uso local: el llavero de quien corre los tests no debe cambiarlo."""
    monkeypatch.setattr(api, "_clave_servicio", lambda: "")


@pytest.fixture(autouse=True)
def turno_libre(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turno, cupos y estado nuevos en cada test, para que uno que los deje tomados no afecte a otro."""
    monkeypatch.setattr(api, "_turno", threading.Lock())
    monkeypatch.setattr(api, "_cupos", threading.BoundedSemaphore(1 + config.COLA_MAXIMA))
    monkeypatch.setattr(api, "_listo", threading.Event())


@pytest.fixture
def llamadas(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Reemplaza `responder()` y anota con qué argumentos se llamó."""
    registro: list[tuple] = []

    def responder(pregunta, etapa=None, filtrar_etapa=False):
        registro.append((pregunta, etapa, filtrar_etapa))
        return Respuesta(resultado="Respuesta.", encontrada=True, confianza="alta", puntaje=0.93)

    monkeypatch.setattr(api, "responder", responder)
    return registro


@pytest.fixture
def sugerencias(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Reemplaza `sugerir()` y anota con qué argumentos se llamó."""
    registro: list[tuple] = []

    def sugerir(etapa, contexto=None, datos_etapa=None):
        registro.append((etapa, contexto, datos_etapa))
        return Respuesta(resultado="**Qué busca esta etapa:** …", encontrada=True, confianza="alta",
                         version_prompt="etapa-v1", puntaje=0.99)

    monkeypatch.setattr(api, "sugerir", sugerir)
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
    assert set(r.json()) == {"modo", "listo", "clave", "almacen", "proveedor_llm", "llm_url", "llm", "embeddings",
                             "reranker", "umbral"}
    assert r.json()["clave"] is False
    assert r.json()["listo"] is False  # nadie ha preguntado y no hubo precarga


def test_salud_no_usa_el_grupo_de_hilos() -> None:
    # Las consultas que esperan turno ocupan hilos; si /salud usara uno, dejaría de
    # responder con la cola llena y el servidor la daría por caída.
    assert inspect.iscoroutinefunction(api.salud)


def test_listo_despues_de_la_primera_consulta(llamadas: list[tuple]) -> None:
    cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué es?"})

    assert cliente.get("/salud").json()["listo"] is True


def test_cola_llena(monkeypatch: pytest.MonkeyPatch, llamadas: list[tuple]) -> None:
    # Sin cupos libres se responde 503 de inmediato, sin esperar turno.
    monkeypatch.setattr(config, "ESPERA_TURNO_S", 60.0)
    cupos = threading.BoundedSemaphore(1)
    cupos.acquire()
    monkeypatch.setattr(api, "_cupos", cupos)

    r = cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué es?"})

    assert r.status_code == 503
    assert r.headers["Retry-After"] == str(api.REINTENTAR_S)
    assert llamadas == []


def test_no_llega_el_turno(monkeypatch: pytest.MonkeyPatch, llamadas: list[tuple]) -> None:
    monkeypatch.setattr(config, "ESPERA_TURNO_S", 0.05)
    api._turno.acquire()  # otra consulta en curso

    r = cliente.post("/ia/sugerir-proximos-pasos", json={"etapa": 7})
    api._turno.release()

    assert r.status_code == 503
    assert "Reintenta" in r.json()["detail"]
    # El cupo se devolvió: con el turno libre, la siguiente se atiende.
    assert cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué es?"}).status_code == 200
    assert llamadas == [("¿Qué es?", None, False)]


def test_error_inesperado(monkeypatch: pytest.MonkeyPatch) -> None:
    def responder(*_args):
        raise KeyError("pagina_inicio")

    monkeypatch.setattr(api, "responder", responder)
    r = TestClient(api.app, raise_server_exceptions=False).post("/ia/consultar-guia", json={"pregunta": "¿Qué es?"})

    assert r.status_code == 500
    assert r.json()["detail"].startswith("Error inesperado")
    assert "pagina_inicio" not in r.text
    assert not api._turno.locked()  # el turno se libera aunque falle


def test_aviso_sin_clave(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.api"), TestClient(api.app):
        pass

    assert "CLAVE_SERVICIO está vacía" in caplog.text


def test_sin_aviso_con_clave(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(api, "_clave_servicio", lambda: "clave-de-prueba")
    with caplog.at_level(logging.WARNING, logger="app.api"), TestClient(api.app):
        pass

    assert "CLAVE_SERVICIO" not in caplog.text


@pytest.mark.parametrize("falla", [False, True])
def test_precarga(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, falla: bool) -> None:
    from app.rag import recuperar

    def precargar() -> None:
        assert api._turno.locked()  # una consulta que llegue mientras tanto espera turno
        if falla:
            raise RuntimeError("El índice está vacío.")

    monkeypatch.setattr(recuperar, "precargar", precargar)
    monkeypatch.setattr(config, "MODO", "local")
    monkeypatch.setattr(config, "PRECARGAR", True)
    with caplog.at_level(logging.INFO, logger="app.api"), TestClient(api.app) as c:
        for hilo in threading.enumerate():  # si ya terminó, no queda ninguno
            if hilo.name == "precarga":
                hilo.join(timeout=5)
        listo = c.get("/salud").json()["listo"]

    assert listo is not falla
    assert not api._turno.locked()
    assert ("No se pudieron precargar" in caplog.text) is falla


@pytest.mark.parametrize("encabezados", [{}, {"Authorization": "Bearer otra"}, {"Authorization": "clave-de-prueba"}])
def test_clave_falta_o_no_es_valida(monkeypatch: pytest.MonkeyPatch, llamadas: list[tuple], encabezados: dict) -> None:
    monkeypatch.setattr(api, "_clave_servicio", lambda: "clave-de-prueba")

    r = cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué es?"}, headers=encabezados)

    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert llamadas == []


def test_clave_valida(monkeypatch: pytest.MonkeyPatch, llamadas: list[tuple]) -> None:
    monkeypatch.setattr(api, "_clave_servicio", lambda: "clave-de-prueba")

    r = cliente.post("/ia/consultar-guia", json={"pregunta": "¿Qué es?"},
                     headers={"Authorization": "Bearer clave-de-prueba"})

    assert r.status_code == 200
    assert cliente.get("/salud").status_code == 200  # /salud no pide clave


@pytest.mark.parametrize("cuerpo, esperado", [
    ({"etapa": 7}, (7, None, None)),
    ({"etapa": 1, "contexto": "Licencias médicas"}, (1, "Licencias médicas", None)),
    ({"etapa": 4, "contexto": {"servicio": "Licencias médicas"}, "datos_etapa": {"mapa_problema_completo": "listo"}},
     (4, {"servicio": "Licencias médicas"}, {"mapa_problema_completo": "listo"})),
])
def test_sugerir_proximos_pasos(sugerencias: list[tuple], cuerpo: dict, esperado: tuple) -> None:
    r = cliente.post("/ia/sugerir-proximos-pasos", json=cuerpo)

    assert r.status_code == 200
    assert set(r.json()) == CAMPOS_CONTRATO
    assert r.json()["version_prompt"] == "etapa-v1"
    assert sugerencias == [esperado]


@pytest.mark.parametrize("cuerpo", [
    {},
    {"etapa": 0},
    {"etapa": 8},
    {"etapa": "siete"},
    {"etapa": 7, "contexto": ["no", "es", "texto"]},
    {"etapa": 7, "datos_etapa": "pendiente"},
])
def test_sugerir_invalida(sugerencias: list[tuple], cuerpo: dict) -> None:
    r = cliente.post("/ia/sugerir-proximos-pasos", json=cuerpo)

    assert r.status_code == 422
    assert sugerencias == []


def test_sugerir_llm_no_disponible(monkeypatch: pytest.MonkeyPatch) -> None:
    def sugerir(*_args):
        raise RuntimeError("El modelo local no está disponible. Inicia Ollama (ollama serve).")

    monkeypatch.setattr(api, "sugerir", sugerir)
    r = cliente.post("/ia/sugerir-proximos-pasos", json={"etapa": 7})

    assert r.status_code == 503
    assert r.json()["detail"] == "El modelo local no está disponible. Inicia Ollama (ollama serve)."


def test_sugerir_pide_la_clave(monkeypatch: pytest.MonkeyPatch, sugerencias: list[tuple]) -> None:
    monkeypatch.setattr(api, "_clave_servicio", lambda: "clave-de-prueba")

    sin_clave = cliente.post("/ia/sugerir-proximos-pasos", json={"etapa": 7})
    con_clave = cliente.post("/ia/sugerir-proximos-pasos", json={"etapa": 7},
                             headers={"Authorization": "Bearer clave-de-prueba"})

    assert sin_clave.status_code == 401
    assert con_clave.status_code == 200
    assert sugerencias == [(7, None, None)]
