"""
Seudonimiza los datos personales de un texto: los reemplaza por marcadores y guarda la tabla
para volver a ponerlos.

    «Paula, RUT 12.345.678-5, paula@ejemplo.cl» → «Paula, RUT [RUT_1], [CORREO_1]»

Los adjuntos traen datos de funcionarios, docentes y personas usuarias. Se
reemplazan antes de fragmentar el texto, convertirlo en vectores o enviarlo al
LLM: así nada de eso queda en el índice ni sale del proceso. La tabla marcador →
valor real queda solo en memoria, junto al adjunto (indice.py), para restaurar
los valores en la respuesta a la misma persona.

Qué se detecta, solo con reglas (sin modelos, sin dependencias):
  RUT        12.345.678-5, 1.234.567-8, 12345678-K. Se valida el dígito verificador
             (módulo 11): un número con guion que no lo cumple no se toca, para no
             confundirlo con un folio.
  CORREO     nombre@dominio.cl
  TELEFONO   móviles (+56 9 1234 5678, 9 1234 5678, 912345678) y fijos con +56
             (+56 2 2345 6789, +56 41 234 5678). Un fijo sin +56 no se reemplaza:
             nueve dígitos sueltos pueden ser un folio o un monto.

Todavía NO se detectan nombres de personas ni direcciones: eso necesita un modelo
de entidades local. El siguiente paso es sumar ese detector con esta misma interfaz.

El mismo valor recibe el mismo marcador en todo el documento, aunque esté escrito
de otra forma (12.345.678-5 y 12345678-5): se compara normalizado. Para eso, al
seudonimizar un documento por secciones se pasan las `correspondencias` que
devolvió la sección anterior.

Prueba rápida, desde backend/:
    echo "RUT 12.345.678-5, ana@ejemplo.cl, +56 9 1234 5678" | python -m app.adjuntos.seudonimizar
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Callable

from app.adjuntos.tipos import Seudonimizado

_RUT = re.compile(r"(?<![\w.])(\d{1,2}\.\d{3}\.\d{3}|\d{7,8})-([\dkK])(?!\w)")
_CORREO = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z\d-]+(?:\.[A-Za-z\d-]+)+(?![\w-])")
_SEP = r"[\s.-]?"
_TELEFONO = re.compile(
    r"(?<![\w+])(?:"
    rf"(?:\+?56{_SEP})?9{_SEP}\d{{4}}{_SEP}\d{{4}}"                     # móvil
    rf"|\+?56{_SEP}(?:2{_SEP}\d{{4}}|[3-7]\d{_SEP}\d{{3}}){_SEP}\d{{4}}"  # fijo, con +56
    r")(?!\d)")
_MARCADOR = re.compile(r"\[(RUT|CORREO|TELEFONO)_(\d+)\]")


def digito_verificador(cuerpo: str) -> str:
    """Dígito verificador del RUT (módulo 11) para los dígitos de `cuerpo`."""
    suma = sum(int(d) * f for d, f in zip(reversed(cuerpo), [2, 3, 4, 5, 6, 7] * 2, strict=False))
    resto = 11 - suma % 11
    return {11: "0", 10: "K"}.get(resto, str(resto))


def _normalizar_rut(valor: str) -> str:
    cuerpo, dv = valor.replace(".", "").upper().split("-")
    return f"{int(cuerpo)}-{dv}"


def _normalizar_telefono(valor: str) -> str:
    digitos = re.sub(r"\D", "", valor)
    return digitos if digitos.startswith("56") and len(digitos) == 11 else f"56{digitos}"


# Orden: los correos primero (pueden traer números) y el RUT antes que el teléfono.
_TIPOS: list[tuple[str, re.Pattern[str], Callable[[str], str]]] = [
    ("CORREO", _CORREO, str.lower),
    ("RUT", _RUT, _normalizar_rut),
    ("TELEFONO", _TELEFONO, _normalizar_telefono),
]
_NORMALIZAR = {tipo: norm for tipo, _, norm in _TIPOS}


def _es_rut_valido(m: re.Match[str]) -> bool:
    return digito_verificador(m.group(1).replace(".", "")) == m.group(2).upper()


def seudonimizar(texto: str, correspondencias: dict[str, str] | None = None) -> Seudonimizado:
    """
    `texto` con RUT, correos y teléfonos reemplazados por [RUT_1], [CORREO_1], [TELEFONO_1]…

    Con `correspondencias` (de una sección anterior del mismo documento), un valor
    ya visto reutiliza su marcador y los nuevos siguen la numeración. Devuelve
    todas las correspondencias, las previas y las nuevas, en un dict nuevo.
    `reemplazos` cuenta solo las apariciones de este texto.
    """
    tabla = dict(correspondencias or {})
    conocidos: dict[tuple[str, str], str] = {}
    siguiente: Counter[str] = Counter()
    for marcador, valor in tabla.items():
        if m := _MARCADOR.fullmatch(marcador):
            tipo = m.group(1)
            conocidos[(tipo, _NORMALIZAR[tipo](valor))] = marcador
            siguiente[tipo] = max(siguiente[tipo], int(m.group(2)))
    reemplazos: Counter[str] = Counter()

    for tipo, patron, normalizar in _TIPOS:
        def reemplazar(m: re.Match[str], tipo: str = tipo, normalizar: Callable[[str], str] = normalizar) -> str:
            if tipo == "RUT" and not _es_rut_valido(m):
                return m.group(0)
            clave = (tipo, normalizar(m.group(0)))
            if clave not in conocidos:
                siguiente[tipo] += 1
                conocidos[clave] = f"[{tipo}_{siguiente[tipo]}]"
                tabla[conocidos[clave]] = m.group(0)
            reemplazos[tipo] += 1
            return conocidos[clave]

        texto = patron.sub(reemplazar, texto)
    return Seudonimizado(texto=texto, correspondencias=tabla, reemplazos=dict(reemplazos))


def restaurar(texto: str, correspondencias: dict[str, str]) -> str:
    """Vuelve a poner los valores reales. Un marcador que no está en la tabla queda como está."""
    return _MARCADOR.sub(lambda m: correspondencias.get(m.group(0), m.group(0)), texto)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ver-correspondencias", action="store_true",
                    help="muestra también los valores reales (no lo uses con datos reales en pantalla compartida)")
    args = ap.parse_args()
    s = seudonimizar(sys.stdin.read())
    print(s.texto)
    print(f"— reemplazos: {s.reemplazos or 'ninguno'}")
    if args.ver_correspondencias:
        for marcador, valor in s.correspondencias.items():
            print(f"   {marcador} = {valor}")


if __name__ == "__main__":
    main()
