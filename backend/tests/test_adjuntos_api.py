"""POST /ia/adjuntos y DELETE /ia/adjuntos/{id}: validación, turno, errores, log y simulador, sin modelos."""
from __future__ import annotations

import logging
import threading

import pytest
from conftest import ADJUNTOS, CAMPOS_ADJUNTO
from fastapi.testclient import TestClient

from app import api
from app.adjuntos.tipos import NO_DISPONIBLE, AdjuntoCargado, ErrorAdjunto
from app.rag import config, simulador

cliente = TestClient(api.app)
DOCX = (ADJUNTOS / "perfil.docx").read_bytes()
TIPO_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def sin_clave_y_turno_libre(monkeypatch: pytest.MonkeyPatch) -> None:
    """Como en test_api.py: sin CLAVE_SERVICIO y con turno, cupos y estado nuevos en cada test."""
    monkeypatch.setattr(api, "_clave_servicio", lambda: "")
    monkeypatch.setattr(api, "_turno", threading.Lock())
    monkeypatch.setattr(api, "_cupos", threading.BoundedSemaphore(1 + config.COLA_MAXIMA))
    monkeypatch.setattr(api, "_listo", threading.Event())


@pytest.fixture
def cargas(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Reemplaza cargar_adjunto() y borrar_adjunto(); anota los nombres que se cargaron."""
    nombres: list[str] = []
    vigentes: set[str] = set()

    def cargar_adjunto(nombre: str, datos: bytes) -> AdjuntoCargado:
        nombres.append(nombre)
        vigentes.add("id-1")
        return AdjuntoCargado(adjunto_id="id-1", nombre=nombre, formato="docx", paginas=None, fragmentos=4,
                              caracteres=1300, reemplazos={"RUT": 2, "CORREO": 1}, expira_en_s=3600,
                              latencia_s=1.2)

    def borrar_adjunto(adjunto_id: str) -> bool:
        if adjunto_id not in vigentes:
            return False
        vigentes.remove(adjunto_id)
        return True

    monkeypatch.setattr(api, "cargar_adjunto", cargar_adjunto)
    monkeypatch.setattr(api, "borrar_adjunto", borrar_adjunto)
    return nombres


def _subir(nombre: str = "perfil.docx", datos: bytes = DOCX, **kwargs):
    return cliente.post("/ia/adjuntos", files={"archivo": (nombre, datos, TIPO_DOCX)}, **kwargs)


def test_subir(cargas: list[str]) -> None:
    r = _subir()

    assert r.status_code == 200
    assert set(r.json()) == CAMPOS_ADJUNTO
    assert r.json()["reemplazos"] == {"RUT": 2, "CORREO": 1}
    assert cargas == ["perfil.docx"]


@pytest.mark.parametrize("nombre, datos, estado", [
    ("perfil.exe", DOCX, 415),
    ("perfil.pdf", DOCX, 415),           # un DOCX con extensión .pdf
    ("vacio.docx", b"", 422),
])
def test_archivo_invalido(cargas: list[str], nombre: str, datos: bytes, estado: int) -> None:
    r = _subir(nombre, datos)

    assert r.status_code == estado
    assert r.json()["detail"]
    assert cargas == []


def test_archivo_sobre_el_tope(monkeypatch: pytest.MonkeyPatch, cargas: list[str]) -> None:
    monkeypatch.setattr(config, "MAX_MB_ADJUNTO", 0.01)

    r = _subir()

    assert r.status_code == 413
    assert "MB" in r.json()["detail"]
    assert cargas == []


def test_sin_archivo() -> None:
    assert cliente.post("/ia/adjuntos").status_code == 422


def test_el_archivo_invalido_no_espera_turno(monkeypatch: pytest.MonkeyPatch, cargas: list[str]) -> None:
    monkeypatch.setattr(config, "ESPERA_TURNO_S", 5.0)
    api._turno.acquire()  # otra consulta en curso

    r = _subir("perfil.exe")

    assert r.status_code == 415  # de inmediato, sin esperar los 5 s del turno


def test_error_al_leer(monkeypatch: pytest.MonkeyPatch) -> None:
    def cargar_adjunto(_nombre, _datos):
        raise ErrorAdjunto("El PDF parece escaneado: no tiene texto que pueda leer.")

    monkeypatch.setattr(api, "cargar_adjunto", cargar_adjunto)
    r = _subir()

    assert r.status_code == 422
    assert r.json()["detail"].startswith("El PDF parece escaneado")
    assert api._turno.acquire(blocking=False)  # el turno quedó libre


def test_modelos_no_disponibles(monkeypatch: pytest.MonkeyPatch) -> None:
    def cargar_adjunto(_nombre, _datos):
        raise RuntimeError("No hay memoria para cargar bge-m3.")

    monkeypatch.setattr(api, "cargar_adjunto", cargar_adjunto)

    assert _subir().status_code == 503


def test_cola_llena(monkeypatch: pytest.MonkeyPatch, cargas: list[str]) -> None:
    cupos = threading.BoundedSemaphore(1)
    cupos.acquire()
    monkeypatch.setattr(api, "_cupos", cupos)

    r = _subir()

    assert r.status_code == 503
    assert r.headers["Retry-After"] == str(api.REINTENTAR_S)
    assert cargas == []


def test_pide_la_clave(monkeypatch: pytest.MonkeyPatch, cargas: list[str]) -> None:
    monkeypatch.setattr(api, "_clave_servicio", lambda: "secreta")

    assert _subir().status_code == 401
    assert cliente.delete("/ia/adjuntos/id-1").status_code == 401
    assert _subir(headers={"Authorization": "Bearer secreta"}).status_code == 200
    assert cargas == ["perfil.docx"]


def test_borrar(cargas: list[str]) -> None:
    adjunto_id = _subir().json()["adjunto_id"]

    assert cliente.delete(f"/ia/adjuntos/{adjunto_id}").status_code == 204
    r = cliente.delete(f"/ia/adjuntos/{adjunto_id}")
    assert r.status_code == 404
    assert r.json()["detail"] == NO_DISPONIBLE


def test_log_sin_el_nombre_del_archivo(cargas: list[str], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.api"):
        _subir("Perfil Paula Rojas.docx")
        _subir("Perfil Paula Rojas.exe")

    ok, rechazo = (r.getMessage() for r in caplog.records)
    for campo in ("ruta=adjuntos", "estado=200", "formato=docx", "kb=", "fragmentos=4", "reemplazos=3",
                  "espera_s=", "latencia_s=1.2"):
        assert campo in ok
    assert rechazo.startswith("ruta=adjuntos estado=415 kb=")
    assert "Paula" not in caplog.text


def test_salud_informa_los_adjuntos() -> None:
    r = cliente.get("/salud").json()

    assert r["formatos_adjunto"] == list(config.FORMATOS_ADJUNTO)
    assert r["max_mb_adjunto"] == config.MAX_MB_ADJUNTO
    assert isinstance(r["adjuntos_vigentes"], int)


@pytest.fixture
def con_simulador(monkeypatch: pytest.MonkeyPatch) -> None:
    """La API con el simulador, como con MODO=simulador."""
    for nombre in ("cargar_adjunto", "borrar_adjunto", "adjuntos_vigentes"):
        monkeypatch.setattr(api, nombre, getattr(simulador, nombre))


def test_simulador(con_simulador: None) -> None:
    r = _subir()
    adjunto_id = r.json()["adjunto_id"]

    assert r.status_code == 200
    assert set(r.json()) == CAMPOS_ADJUNTO
    assert r.json()["modo"] == "simulador"
    assert cliente.get("/salud").json()["adjuntos_vigentes"] >= 1
    assert cliente.delete(f"/ia/adjuntos/{adjunto_id}").status_code == 204
    assert cliente.delete(f"/ia/adjuntos/{adjunto_id}").status_code == 404


@pytest.mark.parametrize("nombre, estado", [
    ("perfil #sin-texto.docx", 422), ("perfil #error.docx", 503), ("perfil.exe", 415),
])
def test_simulador_marcas_y_validacion(con_simulador: None, nombre: str, estado: int) -> None:
    assert _subir(nombre).status_code == estado
