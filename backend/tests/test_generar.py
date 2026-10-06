"""
Umbral, confianza, fuentes y detección del rechazo en `responder()`.

`recuperar()` y la llamada al LLM se reemplazan: lo que se prueba es lo que
decide el backend con los puntajes del reranker, no la calidad de la respuesta.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest
from conftest import CAMPOS_CONTRATO, CAMPOS_FUENTE, fragmento

from app.rag import config, flujo, generar, modelos
from app.rag.contrato import Respuesta
from app.rag.flujo import Tokens
from app.rag.prompts import MENSAJE_NO_ENCONTRADA, SISTEMA, SUGERENCIA, USUARIO, texto_etapa


def _sin_llm(*_args) -> str:
    raise AssertionError("No debería llamarse al LLM.")


@pytest.mark.parametrize("puntaje, esperado", [
    (0.95, "alta"), (0.9, "alta"), (0.89, "media"), (0.7, "media"), (0.69, "baja"), (0.5, "baja"),
])
def test_confianza_por_cortes(puntaje: float, esperado: str) -> None:
    assert flujo.confianza(puntaje) == esperado


def test_bajo_el_umbral_no_llama_al_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: [fragmento(0.42), fragmento(0.1)])
    monkeypatch.setattr(generar, "_generar", _sin_llm)

    r = generar.responder("¿Cuánto presupuesto se necesita?")

    assert r.encontrada is False
    assert r.resultado == f"{MENSAJE_NO_ENCONTRADA} {SUGERENCIA}"
    assert r.confianza is None
    assert r.fuentes == []
    assert r.puntaje == 0.42  # se informa igual, para auditar el umbral


def test_sin_fragmentos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: [])
    monkeypatch.setattr(generar, "_generar", _sin_llm)

    r = generar.responder("¿Algo?")

    assert r.encontrada is False
    assert r.puntaje is None


def test_responde_con_fuentes_de_los_fragmentos_sobre_el_umbral(monkeypatch: pytest.MonkeyPatch) -> None:
    sobre = fragmento(0.93)
    bajo = fragmento(0.3, herramienta=None, actividad=None, seccion="Glosario", pagina_inicio=150,
                     fuente="Glosario, p. 150")
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: [sobre, bajo])
    monkeypatch.setattr(generar, "_generar", lambda pregunta, etapa, nodos: ("Es un diagrama… (fuente)", Tokens()))

    r = generar.responder("¿Qué es un plano del servicio?")

    assert r.encontrada is True
    assert r.confianza == "alta"
    assert r.puntaje == 0.93
    assert len(r.fuentes) == 1  # el fragmento bajo el umbral no se cita
    f = r.fuentes[0]
    assert f["seccion"] == "Plano del servicio"  # la herramienta, que es lo más específico
    assert f["pagina"] == 120
    assert f["fuente"] == "Herramientas › Plano del servicio, p. 120"
    assert f["puntaje"] == 0.93


def test_seccion_de_la_fuente_cae_en_actividad_y_seccion(monkeypatch: pytest.MonkeyPatch) -> None:
    nodos = [fragmento(0.8, herramienta=None), fragmento(0.75, herramienta=None, actividad=None)]
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: nodos)
    monkeypatch.setattr(generar, "_generar", lambda *a: ("Respuesta.", Tokens()))

    r = generar.responder("¿Qué son los momentos críticos?")

    assert [f["seccion"] for f in r.fuentes] == ["Momentos críticos", "Herramientas"]
    assert r.confianza == "media"


def test_rechazo_del_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    # Los fragmentos pasan el umbral, pero el LLM decide que no responden la pregunta.
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: [fragmento(0.8)])
    monkeypatch.setattr(generar, "_generar", lambda *a: (f"{MENSAJE_NO_ENCONTRADA} La guía no trata eso.", Tokens()))

    r = generar.responder("¿Cuál es el sueldo de un diseñador?")

    assert r.encontrada is False
    assert r.confianza is None
    assert r.fuentes == []
    assert r.puntaje == 0.8


@pytest.mark.parametrize("filtrar, etapa_buscada", [(False, None), (True, 7)])
def test_etapa_solo_filtra_si_se_pide(monkeypatch: pytest.MonkeyPatch, filtrar: bool,
                                      etapa_buscada: int | None) -> None:
    llamadas = {}

    def recuperar(pregunta, etapa=None, **kwargs):
        llamadas["etapa"] = etapa
        llamadas["usar_reranker"] = kwargs.get("usar_reranker")
        return [fragmento(0.8)]

    def llm(pregunta, etapa, nodos):
        llamadas["etapa_llm"] = etapa
        return "Respuesta.", Tokens()

    monkeypatch.setattr(generar, "recuperar", recuperar)
    monkeypatch.setattr(generar, "_generar", llm)

    generar.responder("¿Cómo priorizo los momentos?", etapa=7, filtrar_etapa=filtrar)

    assert llamadas["etapa"] == etapa_buscada
    assert llamadas["etapa_llm"] == 7  # al LLM siempre se le indica la etapa
    assert llamadas["usar_reranker"] is True  # el umbral está calibrado sobre el reranker


def test_respuesta_tiene_los_campos_del_contrato(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generar, "recuperar", lambda *a, **k: [fragmento(0.8)])
    monkeypatch.setattr(generar, "_generar", lambda *a: ("Respuesta.", Tokens()))

    r = generar.responder("¿Qué es?").a_dict()
    assert set(r) == CAMPOS_CONTRATO
    assert [set(f) for f in r["fuentes"]] == [CAMPOS_FUENTE]
    assert set(Respuesta(resultado="", encontrada=False, confianza=None).a_dict()) == CAMPOS_CONTRATO


def test_texto_etapa() -> None:
    # Sin etapa, el mensaje de usuario queda igual que en el prompt v3.
    assert texto_etapa(None) == texto_etapa(0) == "no indicada"
    # Con etapa, empieza con el número y el nombre, seguidos del contexto (test_guia.py).
    assert texto_etapa(7).startswith("7 Momentos críticos\n")
    assert texto_etapa(9) == "9"


class _LLMFalso:
    """Reemplaza al cliente de Ollama y guarda los mensajes que recibe."""

    def __init__(self) -> None:
        self.mensajes: list = []

    def chat(self, mensajes: list) -> SimpleNamespace:
        self.mensajes = mensajes
        return SimpleNamespace(message=SimpleNamespace(content=" Respuesta. "), additional_kwargs={},
                               raw={"usage": {"prompt_tokens": 812, "completion_tokens": 95}})


@pytest.mark.parametrize("etapa", [7, None])
def test_mensajes_que_recibe_el_llm(monkeypatch: pytest.MonkeyPatch, etapa: int | None) -> None:
    # Pasa por _generar real: SISTEMA en el mensaje de sistema y la etapa en el de usuario.
    falso = _LLMFalso()
    monkeypatch.setattr(flujo, "llm", lambda: falso)
    nodos = [fragmento(0.8)]

    assert generar._generar("¿Cómo hago el mapa?", etapa, nodos) == ("Respuesta.", Tokens(812, 95))

    sistema, usuario = falso.mensajes
    assert sistema.content == SISTEMA
    assert usuario.content == USUARIO.format(etapa=texto_etapa(etapa), contexto=flujo.contexto(nodos),
                                             pregunta="¿Cómo hago el mapa?")
    if etapa:
        assert "Mapa de momentos críticos" in usuario.content
    else:  # sin etapa, igual que en el prompt v3
        assert usuario.content.startswith("Etapa actual del proyecto (si se conoce): no indicada\n\n<contexto>\n")


@pytest.fixture
def proveedor(monkeypatch: pytest.MonkeyPatch):
    """Cambia PROVEEDOR_LLM y crea de nuevo el cliente del LLM, que se guarda una sola vez por proceso."""
    def cambiar(valor: str) -> None:
        monkeypatch.setattr(config, "PROVEEDOR_LLM", valor)
        modelos.llm.cache_clear()
    yield cambiar
    modelos.llm.cache_clear()


@pytest.mark.parametrize("valor, clase", [("ollama", "Ollama"), ("openai", "OpenAILike")])
def test_cliente_segun_proveedor(proveedor, valor: str, clase: str) -> None:
    proveedor(valor)
    assert type(modelos.llm()).__name__ == clase


def test_proveedor_desconocido(proveedor) -> None:
    proveedor("otro")
    with pytest.raises(ValueError, match="PROVEEDOR_LLM"):
        modelos.llm()


def test_servidor_compatible_con_openai_apagado(proveedor, monkeypatch: pytest.MonkeyPatch) -> None:
    # Nada escucha en el puerto 9: el error dice dónde buscó y qué revisar.
    monkeypatch.setattr(config, "LLM_URL", "http://127.0.0.1:9/v1")
    proveedor("openai")
    with pytest.raises(RuntimeError, match=r"127\.0\.0\.1:9/v1\. Inicia el servidor del modelo y revisa LLM_URL"):
        flujo.chat([])


def test_modelo_que_no_tiene_el_servidor(proveedor, monkeypatch: pytest.MonkeyPatch) -> None:
    proveedor("openai")
    respuesta = httpx.Response(404, request=httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions"))

    def falla(_mensajes: list) -> None:
        raise openai.NotFoundError("model not found", response=respuesta, body=None)

    monkeypatch.setattr(flujo, "llm", lambda: SimpleNamespace(chat=falla))
    with pytest.raises(RuntimeError, match="no tiene el modelo"):
        flujo.chat([])
