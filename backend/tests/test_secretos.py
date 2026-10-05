"""Credenciales en el llavero o, en equipos sin llavero, en .env. Sin tocar el llavero real."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import keyring
import pytest
from dotenv import dotenv_values
from keyring.backends import fail, null

from app.rag import secretos

# Contraseña con lo que puede romper una línea de .env: comillas, #, $, espacios y barras.
URL = "postgresql://postgres.ref:p#a$s'w\"o\\rd $HOME@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"


@pytest.mark.parametrize("backend", [fail.Keyring(), null.Keyring()])
def test_sin_llavero_si_keyring_cae_en_fail_o_null(monkeypatch: pytest.MonkeyPatch,
                                                    backend: keyring.backend.KeyringBackend) -> None:
    # WSL, Linux sin escritorio o un contenedor: keyring no encuentra un llavero real.
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    assert not secretos.hay_llavero()


def test_escribir_env_guarda_el_valor_tal_cual(tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    secretos.escribir_env("SUPABASE_DB_URL", URL, ruta)
    assert dotenv_values(ruta)["SUPABASE_DB_URL"] == URL
    assert secretos.leer_archivo("SUPABASE_DB_URL", ruta) == URL


def test_escribir_env_rechaza_lo_que_dotenv_expandiria(tmp_path: Path) -> None:
    # dotenv reemplaza ${...} incluso entre comillas: se guardaría otra contraseña.
    ruta = tmp_path / ".env"
    with pytest.raises(ValueError, match="entorno"):
        secretos.escribir_env("SUPABASE_DB_URL", "postgresql://u:a${HOME}b@host/db", ruta)
    assert not ruta.exists()


@pytest.mark.skipif(os.name == "nt", reason="en Windows chmod no quita la lectura a otros usuarios")
def test_escribir_env_deja_el_archivo_solo_para_tu_usuario(tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    secretos.escribir_env("SUPABASE_DB_URL", URL, ruta)
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600


def test_escribir_env_reemplaza_la_linea_y_conserva_el_resto(tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    ruta.write_text("ALMACEN=pgvector\n# comentario\nSUPABASE_DB_URL=\nLLM=gemma3:4b", encoding="utf-8")
    secretos.escribir_env("SUPABASE_DB_URL", URL, ruta)
    secretos.escribir_env("CLAVE_SERVICIO", "abc", ruta)
    assert dotenv_values(ruta) == {"ALMACEN": "pgvector", "SUPABASE_DB_URL": URL, "LLM": "gemma3:4b",
                                   "CLAVE_SERVICIO": "abc"}
    assert "# comentario\n" in ruta.read_text(encoding="utf-8")


def test_sin_llavero_guardar_escribe_en_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    monkeypatch.setattr(secretos, "hay_llavero", lambda: False)
    monkeypatch.setattr(secretos, "guardar", lambda *_: pytest.fail("no debe usar el llavero"))
    assert secretos.guardar_donde_se_pueda("SUPABASE_DB_URL", URL, ruta=ruta) == ".env"
    assert secretos.leer_archivo("SUPABASE_DB_URL", ruta) == URL


def test_con_llavero_guarda_ahi_y_vacia_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # .env manda sobre el llavero: si quedara el valor viejo, taparía el nuevo.
    ruta = tmp_path / ".env"
    ruta.write_text("SUPABASE_DB_URL=vieja\n", encoding="utf-8")
    llavero: dict[str, str] = {}
    monkeypatch.setattr(secretos, "hay_llavero", lambda: True)
    monkeypatch.setattr(secretos, "guardar", llavero.__setitem__)
    assert "llavero" in secretos.guardar_donde_se_pueda("SUPABASE_DB_URL", URL, ruta=ruta)
    assert llavero == {"SUPABASE_DB_URL": URL}
    assert secretos.leer_archivo("SUPABASE_DB_URL", ruta) is None


def test_en_env_usa_env_aunque_haya_llavero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    monkeypatch.setattr(secretos, "hay_llavero", lambda: True)
    monkeypatch.setattr(secretos, "guardar", lambda *_: pytest.fail("no debe usar el llavero"))
    assert secretos.guardar_donde_se_pueda("LLM_API_KEY", "sk-prueba", en_env=True, ruta=ruta) == ".env"
    assert secretos.leer_archivo("LLM_API_KEY", ruta) == "sk-prueba"


def test_leer_env_prefiere_la_variable_de_entorno(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ruta = tmp_path / ".env"
    secretos.escribir_env("CLAVE_SERVICIO", "del-archivo", ruta)
    monkeypatch.delenv("CLAVE_SERVICIO", raising=False)
    assert secretos.leer_env("CLAVE_SERVICIO", ruta) == "del-archivo"
    monkeypatch.setenv("CLAVE_SERVICIO", "del-entorno")
    assert secretos.leer_env("CLAVE_SERVICIO", ruta) == "del-entorno"
