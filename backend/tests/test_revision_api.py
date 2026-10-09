"""POST /ia/revisar-entregable: validación, errores, turno, clave y simulador, sin modelos."""
from __future__ import annotations

import threading

import pytest
from conftest import ADJUNTOS, CAMPOS_REVISION
from fastapi.testclient import TestClient

from app import api
from app.adjuntos.tipos import NO_DISPONIBLE, ErrorAdjunto
from app.rag import config, simulador
from app.revision.tipos import CriterioRevisado, Revision

cliente = TestClient(api.app)
CAMPOS_CRITERIO = {"id", "nombre", "tipo", "estado", "evidencia", "sugerencia", "pagina", "cita", "revisado_con"}


@pytest.fixture(autouse=True)
def sin_clave_y_turno_libre(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_clave_servicio", lambda: "")
    monkeypatch.setattr(api, "_turno", threading.Lock())
    monkeypatch.setattr(api, "_cupos", threading.BoundedSemaphore(1 + config.COLA_MAXIMA))
    monkeypatch.setattr(api, "_listo", threading.Event())


@pytest.fixture
def revisiones(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Reemplaza revisar(); anota cada (adjunto_id, herramienta) que se revisó."""
    pedidas: list[tuple[str, str]] = []

    def revisar_entregable(adjunto_id: str, herramienta: str) -> Revision:
        pedidas.append((adjunto_id, herramienta))
        criterio = CriterioRevisado(id="rol", nombre="Rol en el servicio", tipo="obligatorio", estado="cumple",
                                    evidencia="Rol: conductora.", sugerencia="", pagina=148, cita="p. 148, paso 3",
                                    revisado_con="llm")
        return Revision(herramienta=herramienta, nombre="Perfil de persona usuaria", fuente="X, p. 148",
                        version_rubrica="1", rubrica_validada=False, resumen="Perfil de una conductora.",
                        criterios=[criterio], obligatorios=1, obligatorios_cumplidos=1, resultado="✅ Rol",
                        modelo="gemma3:4b", version_prompt="revision-v1", latencia_s=40.0, llamadas_llm=2)

    monkeypatch.setattr(api, "revisar_entregable", revisar_entregable)
    return pedidas


def test_revisar(revisiones: list) -> None:
    r = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "id-1"})

    assert r.status_code == 200
    assert set(r.json()) == CAMPOS_REVISION
    assert set(r.json()["criterios"][0]) == CAMPOS_CRITERIO
    assert revisiones == [("id-1", "perfil_persona_usuaria")]  # herramienta por defecto
    assert api._listo.is_set()


@pytest.mark.parametrize("cuerpo", [{}, {"adjunto_id": ""}, {"adjunto_id": "x" * 65},
                                    {"adjunto_id": "id-1", "herramienta": "plano_del_servicio"}])
def test_solicitud_invalida(revisiones: list, cuerpo: dict) -> None:
    r = cliente.post("/ia/revisar-entregable", json=cuerpo)

    assert r.status_code == 422
    assert revisiones == []


def test_herramienta_inexistente_dice_cuales_hay(revisiones: list) -> None:
    r = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "id-1", "herramienta": "plano_del_servicio"})

    assert "perfil_persona_usuaria" in r.json()["detail"]


def test_adjunto_vencido(monkeypatch: pytest.MonkeyPatch) -> None:
    def revisar_entregable(_adjunto_id, _herramienta):
        raise ErrorAdjunto(NO_DISPONIBLE, 404)

    monkeypatch.setattr(api, "revisar_entregable", revisar_entregable)
    r = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "id-1"})

    assert r.status_code == 404
    assert r.json()["detail"] == NO_DISPONIBLE
    assert api._turno.acquire(blocking=False)  # el turno quedó libre


def test_llm_no_disponible(monkeypatch: pytest.MonkeyPatch) -> None:
    def revisar_entregable(_adjunto_id, _herramienta):
        raise RuntimeError("El modelo no está disponible en http://localhost:11434. Inicia Ollama (ollama serve).")

    monkeypatch.setattr(api, "revisar_entregable", revisar_entregable)
    r = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "id-1"})

    assert r.status_code == 503
    assert r.json()["detail"].endswith("Inicia Ollama (ollama serve).")


def test_cola_llena(monkeypatch: pytest.MonkeyPatch, revisiones: list) -> None:
    cupos = threading.BoundedSemaphore(1)
    cupos.acquire()
    monkeypatch.setattr(api, "_cupos", cupos)

    r = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "id-1"})

    assert r.status_code == 503
    assert revisiones == []


def test_pide_la_clave(monkeypatch: pytest.MonkeyPatch, revisiones: list) -> None:
    monkeypatch.setattr(api, "_clave_servicio", lambda: "secreta")

    sin = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "id-1"})
    con = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "id-1"},
                       headers={"Authorization": "Bearer secreta"})

    assert (sin.status_code, con.status_code) == (401, 200)


@pytest.fixture
def con_simulador(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in ("cargar_adjunto", "borrar_adjunto", "adjuntos_vigentes", "revisar_entregable"):
        monkeypatch.setattr(api, nombre, getattr(simulador, nombre))


def test_simulador(con_simulador: None) -> None:
    docx = (ADJUNTOS / "perfil.docx").read_bytes()
    adjunto_id = cliente.post("/ia/adjuntos", files={"archivo": ("perfil.docx", docx)}).json()["adjunto_id"]

    r = cliente.post("/ia/revisar-entregable", json={"adjunto_id": adjunto_id})
    vencido = cliente.post("/ia/revisar-entregable", json={"adjunto_id": "otro"})

    assert r.status_code == 200
    assert set(r.json()) == CAMPOS_REVISION
    assert r.json()["modo"] == "simulador"
    assert {c["estado"] for c in r.json()["criterios"]} == {"cumple", "parcial", "no_cumple"}
    assert r.json()["resultado"].startswith("**Resumen:**")
    assert vencido.status_code == 404


def test_simulador_usa_la_rubrica() -> None:
    # Cada criterio de la rúbrica tiene su estado simulado, y ninguno «cumple» sin evidencia.
    adjunto = simulador.cargar_adjunto("perfil.docx", (ADJUNTOS / "perfil.docx").read_bytes())
    r = simulador.revisar_entregable(adjunto.adjunto_id)

    assert [c.id for c in r.criterios] == list(simulador.REVISION_PERFIL)
    assert all(c.evidencia for c in r.criterios if c.estado in ("cumple", "parcial"))
    assert r.obligatorios_cumplidos == 2
