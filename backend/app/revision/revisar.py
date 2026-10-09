"""
Revisa un entregable contra la rúbrica de su herramienta: lo que hace POST /ia/revisar-entregable.

    revisar(adjunto_id, herramienta)     adjunto ya subido con POST /ia/adjuntos
      1. rubricas.cargar      lo que pide la guía, punto por punto (data/rubricas/<herramienta>.yaml)
      2. resumen              una llamada al LLM: dos o tres frases sobre lo cargado, sin juicio
      3. cada criterio        `revisa: codigo` → chequeos.CHEQUEOS, sin LLM (si no decide, pasa al LLM)
                              `revisa: llm`    → una llamada con el documento y el punto; responde
                                                 un JSON con evidencia, estado y lo que falta
      4. veredicto()          «cumple» o «parcial» sin evidencia, o con una evidencia que no está
                              en el documento, queda «no_evaluable»: nunca se marca «cumple» sin
                              respaldo. Un JSON inválido también queda «no_evaluable».
      5. restaurar            los marcadores ([RUT_1]) vuelven a su valor en el resumen, la
                              evidencia y las sugerencias: la respuesta va a quien subió el archivo

Qué ve el LLM: el adjunto ya seudonimizado (app/adjuntos/). Si cabe en
MAX_CARACTERES_ENTREGABLE, el documento entero en cada llamada; si no, los TOP_K
fragmentos del adjunto más relevantes para cada punto (indice.buscar, con el
reranker). La página que se cita sale de la rúbrica, no del LLM.

Por qué así: preguntarle al LLM «¿está bien mi documento?» no es repetible ni
auditable. Con un punto por llamada y la evidencia comprobada en el código, cada
veredicto se puede revisar y medir contra una revisión humana. El perfil de
ejemplo son 11 llamadas cortas (el documento se procesa una vez: ver prompts.py):
49 s con gemma3:4b en el Mac M2 de 8 GB (2026-10-09).

Cada revisión deja una línea en el log con la herramienta, los estados, el
número de llamadas, el tiempo y los tokens del LLM, sin el texto del documento.

Prueba rápida, desde backend/ (con un PDF carga los modelos de layout):
    python -m app.revision.revisar tests/datos/adjuntos/perfil.docx
    python -m app.revision.revisar tests/datos/adjuntos/perfil.pdf --json
    python -m app.revision.revisar tests/datos/adjuntos/perfil.docx --ver-prompt   # sin LLM
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from llama_index.core.llms import ChatMessage, MessageRole

from app.adjuntos.tipos import ArchivoExtraido, ErrorAdjunto
from app.rag import config, registro
from app.rag.flujo import Tokens, chat
from app.revision import chequeos, rubricas
from app.revision.prompts import (
    FALTA_PARCIAL,
    FALTA_SIN_PARCIAL,
    OPCION_PARCIAL,
    PARCIAL,
    SISTEMA_REVISION,
    USUARIO_CRITERIO,
    USUARIO_RESUMEN,
    VERSION_PROMPT_REVISION,
    esquema_criterio,
)
from app.revision.tipos import NO_EVALUABLE, CriterioRevisado, Revision, texto_revision

log = logging.getLogger("app.revision")

HERRAMIENTA_POR_DEFECTO = "perfil_persona_usuaria"
# Buscador de fragmentos del adjunto para un punto, cuando el documento no cabe entero.
Buscador = Callable[[str], str]


def para_prompt(texto: str) -> str:
    """El texto de la persona sin «<» ni «>»: así no puede cerrar <documento> y pasar por instrucciones."""
    return texto.replace("<", "‹").replace(">", "›")


def sistema(rubrica: rubricas.Rubrica, documento: str) -> ChatMessage:
    return ChatMessage(role=MessageRole.SYSTEM, content=SISTEMA_REVISION.format(
        herramienta=rubrica.nombre, descripcion=rubrica.descripcion, documento=para_prompt(documento)))


def mensajes_resumen(rubrica: rubricas.Rubrica, documento: str) -> list[ChatMessage]:
    return [sistema(rubrica, documento),
            ChatMessage(role=MessageRole.USER, content=USUARIO_RESUMEN.format(resumen=rubrica.resumen))]


def mensajes_criterio(rubrica: rubricas.Rubrica, criterio: rubricas.Criterio, documento: str) -> list[ChatMessage]:
    con_parcial = criterio.parcial is not None
    usuario = USUARIO_CRITERIO.format(
        nombre=criterio.nombre, pide=criterio.pide,
        parcial=PARCIAL.format(parcial=criterio.parcial) if con_parcial else "",
        opcion_parcial=OPCION_PARCIAL if con_parcial else "",
        falta=FALTA_PARCIAL if con_parcial else FALTA_SIN_PARCIAL)
    return [sistema(rubrica, documento), ChatMessage(role=MessageRole.USER, content=usuario)]


def decidir_sin_llm(criterio: rubricas.Criterio, archivo: ArchivoExtraido) -> tuple[str, str] | None:
    """Estado y evidencia de un criterio `revisa: codigo`; None si es del LLM o el chequeo no decide."""
    chequeo = chequeos.CHEQUEOS.get(criterio.id) if criterio.revisa == "codigo" else None
    return chequeo(archivo) if chequeo else None


def veredicto(criterio: rubricas.Criterio, datos: dict | None, documento: str) -> tuple[str, str, str]:
    """
    Estado, evidencia y sugerencia de un criterio a partir del JSON del LLM.

    Reglas, en este orden:
      - sin JSON o con un estado que no corresponde → no_evaluable
      - no_cumple → sin evidencia, con la sugerencia de la rúbrica
      - cumple o parcial con una evidencia que no está en `documento` → no_evaluable
      - parcial → lo que falta, según el LLM, antes de la sugerencia de la rúbrica
    """
    opciones = ("cumple", "parcial", "no_cumple") if criterio.parcial else ("cumple", "no_cumple")
    estado = datos.get("estado") if datos else None
    if estado not in opciones:
        return "no_evaluable", "", NO_EVALUABLE
    if estado == "no_cumple":
        return "no_cumple", "", criterio.sugerencia
    evidencia = str(datos.get("evidencia") or "").strip()
    if not chequeos.respaldada(evidencia, documento):
        return "no_evaluable", "", NO_EVALUABLE
    if estado == "cumple":
        return "cumple", evidencia, ""
    falta = str(datos.get("falta") or "").strip().rstrip(".")
    return "parcial", evidencia, f"{falta}. {criterio.sugerencia}" if falta else criterio.sugerencia


def _limpiar_resumen(texto: str) -> str:
    """Sin la etiqueta «Resumen:» que a veces antepone el LLM ni saltos de línea."""
    texto = " ".join(texto.replace("**", "").split())
    return texto.split(":", 1)[1].strip() if texto.lower().startswith("resumen:") else texto


def _sumar(tokens: list[Tokens]) -> Tokens:
    prompt = [t.prompt for t in tokens if t.prompt is not None]
    respuesta = [t.respuesta for t in tokens if t.respuesta is not None]
    return Tokens(prompt=sum(prompt) if prompt else None, respuesta=sum(respuesta) if respuesta else None)


def revisar_archivo(archivo: ArchivoExtraido, correspondencias: dict[str, str],
                    herramienta: str = HERRAMIENTA_POR_DEFECTO, buscar: Buscador | None = None) -> Revision:
    """
    Revisa `archivo`, ya seudonimizado, con la rúbrica de `herramienta`.

    Si el texto pasa de MAX_CARACTERES_ENTREGABLE, cada llamada recibe lo que
    devuelve `buscar` para ese punto (los fragmentos más relevantes del adjunto);
    sin `buscar`, ValueError. KeyError si la herramienta no tiene rúbrica;
    RuntimeError si el LLM no está disponible.
    """
    from app.adjuntos.seudonimizar import restaurar

    t0 = time.time()
    rubrica = rubricas.cargar(herramienta)
    completo = archivo.texto()
    entero = len(completo) <= config.MAX_CARACTERES_ENTREGABLE
    if not entero and buscar is None:
        raise ValueError("El documento es largo: hace falta su índice para revisarlo por partes.")

    def documento(consulta: str) -> str:
        return completo if entero else buscar(consulta)

    usos: list[Tokens] = []
    t_llm = 0.0

    def preguntar(mensajes: list[ChatMessage], esquema: dict | None = None) -> str:
        nonlocal t_llm
        t1 = time.time()
        texto, uso = chat(mensajes, esquema)
        t_llm += time.time() - t1
        usos.append(uso)
        return texto

    resumen = _limpiar_resumen(preguntar(mensajes_resumen(rubrica, documento(rubrica.resumen))))
    revisados: list[CriterioRevisado] = []
    for c in rubrica.criterios:
        decidido = decidir_sin_llm(c, archivo)
        if decidido:
            estado, evidencia = decidido
            sugerencia, con = ("" if estado == "cumple" else c.sugerencia), "codigo"
        else:
            texto = preguntar(mensajes_criterio(rubrica, c, documento(f"{c.nombre}: {c.pide}")),
                              esquema_criterio(c.parcial is not None))
            estado, evidencia, sugerencia = veredicto(c, chequeos.leer_veredicto(texto), completo)
            con = "llm"
        revisados.append(CriterioRevisado(
            id=c.id, nombre=c.nombre, tipo=c.tipo, estado=estado,
            evidencia=restaurar(evidencia, correspondencias), sugerencia=restaurar(sugerencia, correspondencias),
            pagina=c.pagina, cita=c.cita(), revisado_con=con))

    resumen = restaurar(resumen, correspondencias)
    obligatorios = [c for c in revisados if c.tipo == "obligatorio"]
    uso = _sumar(usos)
    revision = Revision(
        herramienta=rubrica.id, nombre=rubrica.nombre, fuente=rubrica.fuente, version_rubrica=rubrica.version,
        rubrica_validada=rubrica.validada, resumen=resumen, criterios=revisados,
        obligatorios=len(obligatorios), obligatorios_cumplidos=sum(c.estado == "cumple" for c in obligatorios),
        resultado=texto_revision(rubrica.nombre, rubrica.fuente, resumen, revisados),
        modelo=config.LLM, version_prompt=VERSION_PROMPT_REVISION, latencia_s=round(time.time() - t0, 1),
        tokens_prompt=uso.prompt, tokens_respuesta=uso.respuesta, llamadas_llm=len(usos))
    estados = Counter(c.estado for c in revisados)
    log.info(registro.campos(herramienta=rubrica.id, rubrica=rubrica.version, documento="entero" if entero
                             else "fragmentos", caracteres=len(completo), **{e: estados[e] for e in
                             ("cumple", "parcial", "no_cumple", "no_evaluable")},
                             llamadas_llm=len(usos), t_llm_s=round(t_llm, 1), **uso.campos()))
    return revision


def revisar(adjunto_id: str, herramienta: str = HERRAMIENTA_POR_DEFECTO) -> Revision:
    """
    Revisa el adjunto `adjunto_id`, subido con POST /ia/adjuntos.

    ErrorAdjunto(404) si no existe o venció; KeyError si la herramienta no tiene
    rúbrica; RuntimeError si el LLM no está disponible.
    """
    from app.adjuntos import indice
    from app.rag.flujo import contexto

    rubricas.cargar(herramienta)  # valida la herramienta antes de llamar al LLM
    archivo = indice.archivo(adjunto_id)

    def buscar(consulta: str) -> str:
        return contexto(indice.buscar(adjunto_id, consulta))

    return revisar_archivo(archivo, indice.correspondencias(adjunto_id), herramienta, buscar)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", type=Path, help="entregable (PDF, DOCX o MD)")
    ap.add_argument("--herramienta", default=HERRAMIENTA_POR_DEFECTO,
                    help=f"id de la rúbrica ({', '.join(rubricas.disponibles())})")
    ap.add_argument("--json", action="store_true", help="salida con la forma de la respuesta de la API")
    ap.add_argument("--ver-prompt", action="store_true", help="muestra los mensajes al LLM sin llamarlo")
    args = ap.parse_args()
    registro.configurar()

    from app.adjuntos.cargar import seudonimizar_archivo
    from app.adjuntos.extraer import extraer

    try:
        limpio, tabla, _ = seudonimizar_archivo(extraer(args.archivo.name, args.archivo.read_bytes()))
    except ErrorAdjunto as e:
        sys.exit(f"[{e.estado}] {e.mensaje}")
    rubrica = rubricas.cargar(args.herramienta)

    if args.ver_prompt:
        texto = limpio.texto()[:config.MAX_CARACTERES_ENTREGABLE]
        print(f"===== system\n{sistema(rubrica, texto).content}\n")
        print(f"===== user (resumen)\n{mensajes_resumen(rubrica, texto)[1].content}\n")
        for c in rubrica.criterios:
            if not decidir_sin_llm(c, limpio):
                print(f"===== user ({c.id})\n{mensajes_criterio(rubrica, c, texto)[1].content}\n")
        return

    if len(limpio.texto()) <= config.MAX_CARACTERES_ENTREGABLE:
        r = revisar_archivo(limpio, tabla, args.herramienta)
    else:  # largo: se indexa para revisarlo por partes
        from app.adjuntos.indice import indexar

        r = revisar(indexar(limpio, tabla, {}).adjunto_id, args.herramienta)
    if args.json:
        print(json.dumps(r.a_dict(), ensure_ascii=False, indent=2))
        return
    print(f"\n{r.resultado}\n")
    print(f"— {r.obligatorios_cumplidos} de {r.obligatorios} obligatorios · {r.llamadas_llm} llamadas · "
          f"{r.latencia_s} s · {r.modelo} · prompt {r.version_prompt} · rúbrica {r.version_rubrica}")
    for c in r.criterios:
        print(f"   {c.estado:<12} [{c.revisado_con}] {c.nombre}: {c.evidencia[:100]}")


if __name__ == "__main__":
    main()
