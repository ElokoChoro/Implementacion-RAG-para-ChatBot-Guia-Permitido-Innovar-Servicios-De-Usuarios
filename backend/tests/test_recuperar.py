"""Recuperación sin cargar modelos ni conectarse a Supabase: errores, reranker compartido y caché del índice."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from conftest import fragmento
from sqlalchemy.exc import OperationalError

from app.rag import config, indice, recuperar


def test_sin_conexion_a_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    def indice():
        raise OperationalError("select 1", {}, ConnectionRefusedError("connection refused"))

    monkeypatch.setattr(recuperar, "indice", indice)

    with pytest.raises(RuntimeError, match="No se pudo conectar con el índice en Supabase"):
        recuperar.recuperar("¿Qué es un plano del servicio?")


def test_no_cambia_el_reranker_compartido(monkeypatch: pytest.MonkeyPatch) -> None:
    # reordenador() es una sola instancia por proceso: pedir otro top_k no debe cambiarla.
    class ReordenadorFalso:
        top_n = 4

        def reordenar(self, nodos, pregunta, top_n):
            self.pedido = top_n
            return nodos[:top_n]

    falso = ReordenadorFalso()
    candidatos = [fragmento(0.9)] * config.RERANKER_CANDIDATOS
    monkeypatch.setattr(recuperar, "reordenador", lambda: falso)
    monkeypatch.setattr(recuperar, "indice", lambda: SimpleNamespace(
        as_retriever=lambda **_: SimpleNamespace(retrieve=lambda _pregunta: candidatos)))

    assert len(recuperar.recuperar("¿Qué es?", top_k=2)) == 2
    assert falso.pedido == 2 and falso.top_n == 4


def test_indice_se_abre_una_vez_por_almacen(monkeypatch: pytest.MonkeyPatch) -> None:
    abiertos: list[str] = []
    monkeypatch.setattr(indice, "vector_store", lambda: abiertos.append(config.ALMACEN) or "vs")
    monkeypatch.setattr(indice, "contar", lambda vs: 1)
    monkeypatch.setattr(indice, "_configuracion_indexada", lambda: config.coleccion())
    monkeypatch.setattr(indice, "embedding", lambda: None)
    monkeypatch.setattr(indice.VectorStoreIndex, "from_vector_store", lambda vs, embed_model: f"índice {vs}")
    indice._indice.cache_clear()

    for almacen in ("chroma", "chroma", "pgvector", "pgvector", "chroma"):
        monkeypatch.setattr(config, "ALMACEN", almacen)
        indice.indice()
    indice._indice.cache_clear()

    # Como hace eval/comparar_almacenes.py: cambiar de almacén abre el otro, no reusa el primero.
    assert abiertos == ["chroma", "pgvector"]


def test_indice_vacio_no_queda_en_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    conteos = iter([0, 5])
    monkeypatch.setattr(config, "ALMACEN", "chroma")
    monkeypatch.setattr(indice, "vector_store", lambda: "vs")
    monkeypatch.setattr(indice, "contar", lambda vs: next(conteos))
    monkeypatch.setattr(indice, "embedding", lambda: None)
    monkeypatch.setattr(indice.VectorStoreIndex, "from_vector_store", lambda vs, embed_model: "índice")
    indice._indice.cache_clear()

    with pytest.raises(RuntimeError, match="vacío"):
        indice.indice()
    assert indice.indice() == "índice"  # después de indexar, sin reiniciar
    indice._indice.cache_clear()
