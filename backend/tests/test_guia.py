"""
Etapas de la plataforma (`guia.py`) y el contexto que recibe el LLM en cada una (`prompts.py`).

Los datos de cada etapa se contrastan con el corpus versionado (data/corpus/v3):
las páginas y el objetivo tienen que poder verificarse en la guía, y las etapas
no pueden cambiar sin cambiar el corpus.
"""
from __future__ import annotations

import json
import re
import sys

import pytest

from app.rag import config, guia, prompts

ETAPAS_P1 = [e.numero for e in guia.PROPOSITOS[1].etapas]
# Corpus con que se etiquetaron las ETAPAS: fijo, para no depender de VERSION_CORPUS del .env.
# Si se crea un corpus nuevo junto con un cambio en guia.py, se actualiza aquí en el mismo cambio.
RUTA_CORPUS = config.RAIZ / "data" / "corpus" / "v3" / "paginas.jsonl"


def _corpus() -> dict[int, dict]:
    with RUTA_CORPUS.open(encoding="utf-8") as f:
        return {r["pagina_inicio"]: r for r in map(json.loads, f)}


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).lower()


def test_etapas_del_corpus_sin_cambios() -> None:
    # Con estos valores se etiquetaron data/corpus/v2 y v3: cambiarlos exige una versión nueva del corpus.
    assert guia.ETAPAS == {
        1: "Investigación", 2: "Personas", 3: "Habilitación y Expectativas",
        4: "Necesidades", 5: "Vinculación", 6: "Medición", 7: "Momentos críticos",
    }


def test_paginas_de_cada_etapa_coinciden_con_el_corpus() -> None:
    corpus = _corpus()
    for e in guia.PROPOSITOS[1].etapas:
        inicio, fin = e.paginas
        etiquetadas = {n for n, r in corpus.items() if r["etapa"] == e.numero}
        assert etiquetadas == {n for n in corpus if inicio <= n <= fin}, e.nombre
        assert all(corpus[n]["actividad"] == e.actividad for n in etiquetadas)


@pytest.mark.parametrize("numero, paginas, herramientas", [
    (1, (108, 111), [(110, "Plan de investigación de experiencia usuaria")]),
    (2, (140, 149), [(142, "Mapa de perfiles de personas usuarias"), (148, "Perfil de persona usuaria")]),
    (3, (100, 103), [(102, "Mapa de expectativas")]),
    (4, (132, 139), [(134, "Mapa del problema completo"), (136, "Pilares del servicio")]),
    (5, (154, 157), [(156, "Matriz de vinculación entre necesidades y servicios")]),
    (6, (116, 119), [(118, "Plan de evaluación de estándares de servicio")]),
    (7, (126, 131), [(128, "Mapa de momentos críticos")]),
])
def test_paginas_y_herramientas(numero: int, paginas: tuple[int, int], herramientas: list) -> None:
    e = guia.etapa(numero)
    assert e.paginas == paginas
    assert e.herramientas == herramientas


def test_herramientas_empiezan_en_paginas_del_corpus() -> None:
    corpus = _corpus()
    for e in guia.PROPOSITOS[1].etapas:
        for pagina, nombre in e.herramientas:
            assert corpus[pagina]["herramienta"] == nombre


def test_objetivo_se_verifica_en_la_guia() -> None:
    # La primera parte de cada objetivo es la línea de la actividad en la lista del Propósito 1 (p. 30).
    corpus = _corpus()
    for e in guia.PROPOSITOS[1].etapas:
        assert all(p in corpus for p in e.paginas_objetivo), e.nombre
        linea = re.split(r":|, para ", e.objetivo)[0]
        assert _normalizar(linea) in _normalizar(corpus[30]["texto"]), e.nombre


def test_actividad_desconocida() -> None:
    with pytest.raises(ValueError, match="no está en ACTIVIDADES"):
        guia.paginas_actividad("Actividad inexistente")


def test_etapa_inexistente() -> None:
    assert guia.etapa(8) is None
    assert guia.etapa(1, proposito=2) is None  # los Propósitos 2 a 5 todavía no tienen datos


@pytest.mark.parametrize("numero", ETAPAS_P1)
def test_contexto_de_la_etapa(numero: int) -> None:
    e = guia.etapa(numero)
    texto = prompts.texto_etapa(numero)
    assert texto.startswith(f"{e.numero} {e.nombre}\n")
    assert e.actividad in texto and e.objetivo in texto
    assert all(nombre in texto for _, nombre in e.herramientas)
    # Sin páginas: la regla 1 del prompt exige citar solo las líneas «fuente:» de los fragmentos.
    assert not re.search(r"\b(?:pp?|págs?|pags?)\.\s*\d", texto)
    # Corto, por gemma3:4b en un Mac de 8 GB.
    assert 80 <= len(texto.split()) <= 120


def test_contexto_va_en_el_mensaje_de_usuario() -> None:
    mensaje = prompts.USUARIO.format(etapa=prompts.texto_etapa(7), contexto="…", pregunta="¿Cómo hago el mapa?")
    assert "Mapa de momentos críticos" in mensaje
    assert "Mapa de momentos críticos" not in prompts.SISTEMA


def test_cli_muestra_la_etapa(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(sys, "argv", ["prompts", "--etapa", "7"])
    prompts.main()
    salida = capsys.readouterr().out
    assert "págs. 126-131" in salida
    assert "Mapa de momentos críticos, p. 128" in salida


@pytest.mark.parametrize("numero", ["0", "9"])
def test_cli_etapa_inexistente(monkeypatch: pytest.MonkeyPatch, numero: str) -> None:
    monkeypatch.setattr(sys, "argv", ["prompts", "--etapa", numero])
    with pytest.raises(SystemExit, match=f"no tiene etapa {numero}"):
        prompts.main()
