"""
Validación y extracción de adjuntos.

DOCX y MD se convierten de verdad: Docling los lee con backends simples, sin
modelos. Los PDF solo se validan y se abren con pypdfium2 (sin modelos); la
conversión con el layout de Docling se prueba con la CLI de extraer.py.
"""
from __future__ import annotations

import pytest
from conftest import ADJUNTOS

from app.adjuntos import extraer as ex
from app.adjuntos.tipos import ErrorAdjunto, Seccion
from app.rag import config


def _leer(nombre: str) -> bytes:
    return (ADJUNTOS / nombre).read_bytes()


@pytest.fixture
def con_md(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FORMATOS_ADJUNTO", ("pdf", "docx", "md"))


def test_valida_los_formatos_aceptados() -> None:
    assert ex.validar("Perfil.DOCX", _leer("perfil.docx")) == "docx"
    assert ex.validar("perfil.pdf", _leer("perfil.pdf")) == "pdf"


def test_md_solo_si_esta_en_la_configuracion(con_md: None, monkeypatch: pytest.MonkeyPatch) -> None:
    assert ex.validar("perfil.md", _leer("perfil.md")) == "md"
    monkeypatch.setattr(config, "FORMATOS_ADJUNTO", ("pdf", "docx"))
    with pytest.raises(ErrorAdjunto) as e:
        ex.validar("perfil.md", _leer("perfil.md"))
    assert e.value.estado == 415
    assert "PDF o DOCX" in e.value.mensaje


@pytest.mark.parametrize("nombre, datos, estado", [
    ("no-es-pdf.pdf", (ADJUNTOS / "no-es-pdf.pdf").read_bytes(), 415),
    ("perfil.docx", (ADJUNTOS / "perfil.pdf").read_bytes(), 415),   # un PDF con extensión .docx
    ("programa.exe", b"MZ\x90\x00", 415),
    ("sin-extension", b"%PDF-1.4", 415),
    ("vacio.pdf", b"", 422),
])
def test_rechaza_archivos_invalidos(nombre: str, datos: bytes, estado: int) -> None:
    with pytest.raises(ErrorAdjunto) as e:
        ex.validar(nombre, datos)
    assert e.value.estado == estado


def test_md_binario_no_es_md(con_md: None) -> None:
    with pytest.raises(ErrorAdjunto) as e:
        ex.validar("notas.md", b"texto\x00binario")
    assert e.value.estado == 415


def test_rechaza_archivos_sobre_el_tope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MAX_MB_ADJUNTO", 0.01)  # ~10 KB; perfil.pdf pesa más
    with pytest.raises(ErrorAdjunto) as e:
        ex.validar("perfil.pdf", _leer("perfil.pdf"))
    assert e.value.estado == 413
    assert "0.01 MB" in e.value.mensaje


@pytest.mark.parametrize("caracteres, escaneado", [
    ([], True), ([0], True), ([10, 20, 5], True), ([0, 0, 200], False), ([1200, 900], False),
])
def test_regla_de_pdf_escaneado(caracteres: list[int], escaneado: bool) -> None:
    assert ex.es_escaneado(caracteres) is escaneado


def test_texto_crudo_y_tope_de_paginas(monkeypatch: pytest.MonkeyPatch) -> None:
    crudo = ex._texto_crudo_pdf(_leer("perfil.pdf"))
    assert len(crudo) == 3
    assert "SEGUIMIENTO" in crudo[2]

    monkeypatch.setattr(config, "MAX_PAGINAS_ADJUNTO", 2)
    with pytest.raises(ErrorAdjunto) as e:
        ex._texto_crudo_pdf(_leer("perfil.pdf"))
    assert e.value.estado == 413


def test_pdf_escaneado_se_rechaza_sin_cargar_docling(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_cargar(*_args):
        raise AssertionError("no debe convertir con Docling un PDF sin texto")

    monkeypatch.setattr(ex, "_convertir", no_cargar)
    with pytest.raises(ErrorAdjunto) as e:
        ex.extraer("escaneado.pdf", _leer("escaneado.pdf"))
    assert e.value.estado == 422
    assert "escaneado" in e.value.mensaje


def test_pdf_usa_el_texto_crudo_si_docling_se_salta_una_pagina(monkeypatch: pytest.MonkeyPatch) -> None:
    class DocSinPagina3:
        def export_to_markdown(self, page_no: int, **_kwargs) -> str:
            return "" if page_no == 3 else f"## Título {page_no}\n\n" + "texto de Docling " * 30

    monkeypatch.setattr(ex, "_convertir", lambda *_args: DocSinPagina3())
    archivo = ex.extraer("perfil.pdf", _leer("perfil.pdf"))

    assert archivo.paginas == 3
    assert [s.pagina for s in archivo.secciones] == [1, 2, 3]
    assert archivo.secciones[0].titulo == "Título 1"
    assert "SEGUIMIENTO" in archivo.secciones[2].texto       # del texto crudo
    assert archivo.secciones[2].titulo == "Título 2"         # el último título visto


def test_extrae_docx_por_titulos() -> None:
    archivo = ex.extraer("perfil.docx", _leer("perfil.docx"))

    assert archivo.formato == "docx"
    assert archivo.paginas is None
    assert [s.titulo for s in archivo.secciones] == [
        "Perfil de persona usuaria", "Proyecto", "Perfil: persona mayor que renueva su licencia", "Seguimiento"]
    assert all(s.pagina is None for s in archivo.secciones)
    assert "| Canal preferido" in archivo.texto()  # la tabla, en markdown
    assert archivo.caracteres() > 1000


def test_extrae_md(con_md: None) -> None:
    archivo = ex.extraer("perfil.md", _leer("perfil.md"))

    assert archivo.formato == "md"
    assert len(archivo.secciones) == 4
    assert "12.345.678-5" in archivo.texto()


def test_docx_danado(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<esto no es xml de Word")
    with pytest.raises(ErrorAdjunto) as e:
        ex.extraer("roto.docx", buf.getvalue())
    assert e.value.estado == 422


def test_secciones_por_titulo() -> None:
    markdown = "Intro sin título\n\n# Uno\n\nTexto uno\n\n## Vacío\n## Dos ##\n\nTexto dos\n"

    assert ex.secciones_por_titulo(markdown) == [
        Seccion(texto="Intro sin título"),
        Seccion(texto="Uno\n\nTexto uno", titulo="Uno"),
        Seccion(texto="Dos\n\nTexto dos", titulo="Dos"),
    ]
