"""Rúbricas de data/rubricas/: que carguen, que citen la guía y que fallen claro si tienen un error."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.revision import chequeos, rubricas

CORPUS = Path(__file__).resolve().parents[2] / "data" / "corpus" / "v3" / "paginas.jsonl"


@pytest.fixture(autouse=True)
def sin_cache() -> Iterator[None]:
    rubricas.cargar.cache_clear()
    yield
    rubricas.cargar.cache_clear()


@pytest.mark.parametrize("herramienta", rubricas.disponibles())
def test_cada_rubrica_carga(herramienta: str) -> None:
    r = rubricas.cargar(herramienta)

    assert r.id == herramienta
    assert r.obligatorios()
    # Los criterios que revisa el código tienen su chequeo.
    assert {c.id for c in r.criterios if c.revisa == "codigo"} <= set(chequeos.CHEQUEOS)


@pytest.mark.parametrize("herramienta", rubricas.disponibles())
def test_cita_la_guia_como_el_corpus(herramienta: str) -> None:
    # La fuente de la herramienta tiene que existir tal cual en las líneas «fuente:» del corpus.
    fuentes = {json.loads(linea)["fuente"] for linea in CORPUS.open(encoding="utf-8")}

    assert rubricas.cargar(herramienta).fuente in fuentes


def test_perfil_tiene_las_preguntas_de_la_lamina() -> None:
    r = rubricas.cargar("perfil_persona_usuaria")

    assert [c.id for c in r.obligatorios()] == ["rol", "necesidades", "expectativas", "relacion", "variables"]
    assert r.fuente == "Personas › Perfil de persona usuaria, p. 148"
    assert all(c.pagina == 148 and c.paso for c in r.criterios)
    assert r.criterios[0].cita() == "p. 148, paso 3"
    assert "  " not in r.criterios[0].pide  # el YAML junta las líneas con un espacio


def test_no_existe() -> None:
    with pytest.raises(KeyError, match="perfil_persona_usuaria"):
        rubricas.cargar("plano_del_servicio")


def _rubrica(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, criterio: str) -> None:
    monkeypatch.setattr(rubricas, "RUTA_RUBRICAS", tmp_path)
    (tmp_path / "prueba.yaml").write_text(
        "id: prueba\nnombre: Prueba\nversion: '1'\nfuente: X, p. 1\npagina: 1\ndescripcion: d\nresumen: r\n"
        f"criterios:\n  - {criterio}\n", encoding="utf-8")


@pytest.mark.parametrize("criterio, error", [
    ("{id: a, nombre: A, tipo: opcional, revisa: llm, pagina: 1, pide: p, sugerencia: s}", "tipo"),
    ("{id: a, nombre: A, tipo: obligatorio, revisa: humano, pagina: 1, pide: p, sugerencia: s}", "revisa"),
    ("{id: a, nombre: A, tipo: obligatorio, revisa: llm, pagina: 400, pide: p, sugerencia: s}", "p. 400"),
    ("{id: a, nombre: A, tipo: obligatorio, revisa: llm, pagina: 1, pide: p}", "sugerencia"),
])
def test_error_en_el_archivo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, criterio: str, error: str) -> None:
    _rubrica(tmp_path, monkeypatch, criterio)

    with pytest.raises(ValueError, match=error):
        rubricas.cargar("prueba")
