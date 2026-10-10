"""Chequeos sin LLM de la revisión: cantidad de perfiles, evidencia respaldada y lectura del JSON."""
from __future__ import annotations

import pytest

from app.adjuntos.extraer import secciones_por_titulo
from app.adjuntos.tipos import ArchivoExtraido, Seccion
from app.revision.chequeos import cantidad_de_perfiles, leer_veredicto, normalizar, respaldada, titulos_de_perfil

DOCUMENTO = ("Rol: conductora de 68 años que renueva su licencia cada tres años.\n\n"
             "**Necesidades:** saber qué documentos llevar antes de viajar a la municipalidad.\n\n"
             "| Canal preferido | Teléfono y atención presencial |")


def _archivo(markdown: str) -> ArchivoExtraido:
    return ArchivoExtraido(nombre="perfil.md", formato="md", secciones=secciones_por_titulo(markdown))


def test_normalizar() -> None:
    assert normalizar("**Expectativas del PROCESO:** que la atiendan…") == "expectativas del proceso que la atiendan"
    assert normalizar("RUT [RUT_1]") == "rut [rut_1]"


@pytest.mark.parametrize("cita", [
    "conductora de 68 años que renueva su licencia cada tres años.",
    "Necesidades: saber qué documentos llevar",            # sin el markdown del documento
    "CONDUCTORA DE 68 ANOS",                               # mayúsculas y sin tilde
    "conductora de 68 años … cada tres años",              # con partes omitidas
    "Canal preferido: Teléfono y atención presencial",     # celdas de una tabla
    "Rol: conductora de 68 años que renueva su licencia cada tres años, en Villa",  # un agregado al final
])
def test_respaldada(cita: str) -> None:
    assert respaldada(cita, DOCUMENTO)


@pytest.mark.parametrize("cita", [
    "",
    "Rol",                                                  # demasiado corta para respaldar algo
    "La persona usa el servicio de forma obligatoria.",     # no está en el documento
    "Necesita conocer los requisitos antes de ir a la oficina.",  # paráfrasis
])
def test_no_respaldada(cita: str) -> None:
    assert not respaldada(cita, DOCUMENTO)


@pytest.mark.parametrize("texto", [
    '{"evidencia": "x", "estado": "cumple", "falta": ""}',
    'Aquí está:\n```json\n{"evidencia": "x", "estado": "cumple", "falta": ""}\n```',
])
def test_leer_veredicto(texto: str) -> None:
    assert leer_veredicto(texto) == {"evidencia": "x", "estado": "cumple", "falta": ""}


@pytest.mark.parametrize("texto", ["", "cumple", '{"estado": cumple}', "[1, 2]"])
def test_veredicto_invalido(texto: str) -> None:
    assert leer_veredicto(texto) is None


def test_un_perfil() -> None:
    archivo = _archivo("# Perfil de persona usuaria\n\nProyecto X.\n\n## Perfil: persona mayor\n\nRol: conductora.")

    assert titulos_de_perfil(archivo) == ["Perfil: persona mayor"]  # sin el título general
    assert cantidad_de_perfiles(archivo) == ("cumple", "El documento describe un perfil: «Perfil: persona mayor».")


@pytest.mark.parametrize("cantidad, estado", [(2, "no_cumple"), (3, "cumple"), (5, "cumple"), (6, "no_cumple")])
def test_varios_perfiles(cantidad: int, estado: str) -> None:
    archivo = _archivo("# Perfiles de personas usuarias\n\nIntro.\n\n"
                       + "\n\n".join(f"## Perfil {i}: Persona {i}\n\nRol: {i}." for i in range(1, cantidad + 1)))

    resultado = cantidad_de_perfiles(archivo)

    assert resultado is not None and resultado[0] == estado
    assert f"describe {cantidad} perfiles" in resultado[1]


def test_titulos_dentro_del_texto() -> None:
    # En un PDF, cada sección es una página y los títulos quedan en el texto como «##».
    archivo = ArchivoExtraido(nombre="p.pdf", formato="pdf", paginas=1, secciones=[
        Seccion(texto="## Perfil 1: Rosa\n\nRol: a.\n\n## Perfil 2: Juan\n\nRol: b.", pagina=1,
                titulo="Perfil 1: Rosa"),
    ])

    assert titulos_de_perfil(archivo) == ["Perfil 1: Rosa", "Perfil 2: Juan"]


def test_sin_titulos_no_decide() -> None:
    assert cantidad_de_perfiles(_archivo("Rol: conductora.\n\nNecesidades: saber qué llevar.")) is None
