"""Carga de un adjunto: extraer → seudonimizar cada sección y título → indexar (sin modelos)."""
from __future__ import annotations

import re

import pytest
from conftest import ADJUNTOS

from app.adjuntos import cargar
from app.adjuntos.tipos import AdjuntoCargado, ArchivoExtraido, Seccion


def test_seudonimiza_secciones_y_titulos_con_los_mismos_marcadores() -> None:
    archivo = ArchivoExtraido(nombre="x.pdf", formato="pdf", paginas=2, secciones=[
        Seccion("Encargada: RUT 12.345.678-5, ana@ejemplo.cl", pagina=1, titulo="Contacto 912345678"),
        Seccion("Repite 12345678-5 y llama al +56 9 1234 5678", pagina=2),
    ])
    limpio, tabla, reemplazos = cargar.seudonimizar_archivo(archivo)

    assert limpio.secciones[0] == Seccion("Encargada: RUT [RUT_1], [CORREO_1]", pagina=1,
                                          titulo="Contacto [TELEFONO_1]")
    assert limpio.secciones[1].texto == "Repite [RUT_1] y llama al [TELEFONO_1]"
    assert reemplazos == {"RUT": 2, "CORREO": 1, "TELEFONO": 2}
    assert set(tabla) == {"[RUT_1]", "[CORREO_1]", "[TELEFONO_1]"}
    assert (limpio.nombre, limpio.paginas) == ("x.pdf", 2)


def test_cargar_adjunto_indexa_el_texto_seudonimizado(monkeypatch: pytest.MonkeyPatch) -> None:
    recibido: dict = {}

    def indexar(archivo, correspondencias, reemplazos):
        recibido.update(archivo=archivo, tabla=correspondencias)
        return AdjuntoCargado(adjunto_id="a", nombre=archivo.nombre, formato=archivo.formato,
                              paginas=archivo.paginas, fragmentos=4, caracteres=archivo.caracteres(),
                              reemplazos=reemplazos)

    monkeypatch.setattr(cargar, "indexar", indexar)
    adjunto = cargar.cargar_adjunto("perfil.docx", (ADJUNTOS / "perfil.docx").read_bytes())

    assert adjunto.reemplazos == {"RUT": 2, "CORREO": 1, "TELEFONO": 1}
    assert adjunto.latencia_s >= 0
    assert not re.search(r"12\.?345\.?678-5|@ejemplo\.cl|1234 5678", recibido["archivo"].texto())
    assert "12.345.678-5" in recibido["tabla"].values()
