"""Errores de la recuperación que la API responde como 503, sin cargar modelos ni conectarse a Supabase."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.rag import recuperar


def test_sin_conexion_a_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    def indice():
        raise OperationalError("select 1", {}, ConnectionRefusedError("connection refused"))

    monkeypatch.setattr(recuperar, "indice", indice)

    with pytest.raises(RuntimeError, match="No se pudo conectar con el índice en Supabase"):
        recuperar.recuperar("¿Qué es un plano del servicio?")
