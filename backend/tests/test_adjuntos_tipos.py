"""Tipos de los adjuntos: contrato de POST /ia/adjuntos, configuración y que no importan modelos."""
from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path

from conftest import CAMPOS_ADJUNTO

from app.adjuntos.tipos import AdjuntoCargado, ArchivoExtraido, ErrorAdjunto, Seccion

BACKEND = Path(__file__).resolve().parents[1]
TIPOS_TS = BACKEND.parent / "src" / "types.ts"


def test_adjunto_cargado_tiene_los_campos_del_contrato() -> None:
    adjunto = AdjuntoCargado(adjunto_id="a", nombre="perfil.docx", formato="docx", paginas=None,
                             fragmentos=3, caracteres=900)

    assert {f.name for f in dataclasses.fields(AdjuntoCargado)} == CAMPOS_ADJUNTO
    assert set(adjunto.a_dict()) == CAMPOS_ADJUNTO


def test_el_tipo_del_frontend_tiene_los_mismos_campos() -> None:
    bloque = re.search(r"export type AdjuntoCargado = \{(.*?)\n\}", TIPOS_TS.read_text(encoding="utf-8"), re.S)

    assert bloque, "falta AdjuntoCargado en src/types.ts"
    assert set(re.findall(r"^\s+(\w+):", bloque.group(1), re.M)) == CAMPOS_ADJUNTO


def test_error_guarda_mensaje_y_estado() -> None:
    e = ErrorAdjunto("Solo puedo leer archivos PDF o DOCX.", 415)

    assert (str(e), e.mensaje, e.estado) == ("Solo puedo leer archivos PDF o DOCX.",) * 2 + (415,)
    assert ErrorAdjunto("No pude leerlo.").estado == 422


def test_texto_y_caracteres_del_archivo() -> None:
    archivo = ArchivoExtraido(nombre="perfil.pdf", formato="pdf", paginas=2,
                              secciones=[Seccion("Hola", pagina=1), Seccion("mundo", pagina=2)])

    assert archivo.texto() == "Hola\n\nmundo"
    assert archivo.caracteres() == len("Hola\n\nmundo")


def _config(formatos: str) -> subprocess.CompletedProcess:
    codigo = "from app.rag import config; print(','.join(config.FORMATOS_ADJUNTO))"
    return subprocess.run([sys.executable, "-c", codigo], cwd=BACKEND, capture_output=True, text=True,
                          env={**os.environ, "FORMATOS_ADJUNTO": formatos})


def test_formatos_de_la_configuracion() -> None:
    assert _config(" PDF, .docx ,md").stdout.strip() == "pdf,docx,md"
    invalido = _config("pdf,exe")
    assert invalido.returncode != 0
    assert "FORMATOS_ADJUNTO" in invalido.stderr


def test_tipos_y_config_no_importan_modelos() -> None:
    # En un proceso aparte: aquí conftest ya importó LlamaIndex. Los usa el simulador.
    codigo = ("import sys, app.adjuntos.tipos, app.rag.config; "
              "print(sorted({m.split('.')[0] for m in sys.modules} & "
              "{'llama_index', 'FlagEmbedding', 'torch', 'docling'}))")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=BACKEND, capture_output=True, text=True,
                            check=True).stdout

    assert salida.strip() == "[]"
