"""Seudonimización de RUT, correos y teléfonos, con marcadores consistentes en todo el documento."""
from __future__ import annotations

import re

import pytest
from conftest import ADJUNTOS

from app.adjuntos.seudonimizar import digito_verificador, restaurar, seudonimizar


@pytest.mark.parametrize("cuerpo, dv", [("12345678", "5"), ("7654321", "6"), ("11111111", "1"),
                                        ("10000013", "K"), ("1000005", "K")])
def test_digito_verificador(cuerpo: str, dv: str) -> None:
    assert digito_verificador(cuerpo) == dv


@pytest.mark.parametrize("rut", ["12.345.678-5", "12345678-5", "7.654.321-6", "7654321-6", "10.000.013-K",
                                 "10000013-k"])
def test_reemplaza_ruts_validos(rut: str) -> None:
    s = seudonimizar(f"RUT {rut}.")

    assert s.texto == "RUT [RUT_1]."
    assert s.correspondencias == {"[RUT_1]": rut}
    assert s.reemplazos == {"RUT": 1}


def test_no_toca_un_rut_con_digito_verificador_incorrecto() -> None:
    assert seudonimizar("Folio 12.345.678-9").texto == "Folio 12.345.678-9"


def test_el_mismo_rut_en_dos_formatos_tiene_un_marcador() -> None:
    s = seudonimizar("Encargada 12.345.678-5; dudas a 12345678-5.")

    assert s.texto == "Encargada [RUT_1]; dudas a [RUT_1]."
    assert s.reemplazos == {"RUT": 2}


@pytest.mark.parametrize("correo", ["ana@ejemplo.cl", "ana.p+uxlab@sub.gob.cl", "Ana_P@Ejemplo.CL"])
def test_reemplaza_correos(correo: str) -> None:
    assert seudonimizar(f"Escribe a {correo}, por favor.").texto == "Escribe a [CORREO_1], por favor."


@pytest.mark.parametrize("telefono", ["+56 9 1234 5678", "+56912345678", "9 1234 5678", "912345678",
                                      "+56 2 2345 6789", "+56 41 234 5678", "56-9-1234-5678"])
def test_reemplaza_telefonos(telefono: str) -> None:
    assert seudonimizar(f"Llama al {telefono}.").texto == "Llama al [TELEFONO_1]."


def test_el_mismo_telefono_escrito_distinto_tiene_un_marcador() -> None:
    assert seudonimizar("+56 9 1234 5678 o 912345678").texto == "[TELEFONO_1] o [TELEFONO_1]"


@pytest.mark.parametrize("texto", [
    "En 2026 se entrevistó a 12 personas.",
    "El monto es $12.345.678 y el folio 123456789.",
    "Fijo sin código: 2 2345 6789.",
    "Ver páginas 110, 128 y 148.",
    "Sin datos personales.",
])
def test_no_reemplaza_lo_que_no_es_dato_personal(texto: str) -> None:
    s = seudonimizar(texto)

    assert s.texto == texto
    assert s.reemplazos == {}
    assert s.correspondencias == {}


def test_marcadores_consistentes_entre_secciones() -> None:
    primera = seudonimizar("RUT 12.345.678-5, ana@ejemplo.cl")
    segunda = seudonimizar("Otra vez 12345678-5 y nuevo 7.654.321-6, ana@ejemplo.cl", primera.correspondencias)

    assert segunda.texto == "Otra vez [RUT_1] y nuevo [RUT_2], [CORREO_1]"
    assert segunda.reemplazos == {"RUT": 2, "CORREO": 1}
    assert set(segunda.correspondencias) == {"[RUT_1]", "[RUT_2]", "[CORREO_1]"}
    assert primera.correspondencias == {"[CORREO_1]": "ana@ejemplo.cl", "[RUT_1]": "12.345.678-5"}  # sin mutar


def test_ida_y_vuelta_con_diez_marcadores() -> None:
    ruts = [f"{c}-{digito_verificador(str(c))}" for c in range(10_000_001, 10_000_011)]
    texto = "Lista: " + ", ".join(ruts) + ". Primero otra vez: " + ruts[0]
    s = seudonimizar(texto)

    assert "[RUT_1]" in s.texto and "[RUT_10]" in s.texto
    assert restaurar(s.texto, s.correspondencias) == texto


def test_restaurar_deja_marcadores_desconocidos() -> None:
    assert restaurar("[RUT_1] y [RUT_2]", {"[RUT_1]": "12.345.678-5"}) == "12.345.678-5 y [RUT_2]"


def test_el_ejemplo_no_conserva_datos_personales() -> None:
    texto = (ADJUNTOS / "perfil.md").read_text(encoding="utf-8")
    s = seudonimizar(texto)

    assert not re.search(r"12\.?345\.?678-5|@ejemplo\.cl|1234 5678", s.texto)
    assert s.reemplazos == {"RUT": 2, "CORREO": 1, "TELEFONO": 1}
    assert len(s.correspondencias) == 3
