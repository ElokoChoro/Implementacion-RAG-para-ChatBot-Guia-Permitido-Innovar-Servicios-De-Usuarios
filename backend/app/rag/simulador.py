"""
Simulador de `POST /ia/consultar-guia`, `POST /ia/sugerir-proximos-pasos`,
`POST /ia/adjuntos` y `POST /ia/revisar-entregable`: respuestas fijas, sin modelos
(MODO=simulador).

Sirve para que la plataforma integre la API antes de tener los modelos a mano:
devuelve una `Respuesta` (contrato.py) con los mismos campos, la misma
validación y los mismos errores que generar.py y sugerir.py, pero no importa LlamaIndex,
FlagEmbedding ni el cliente del LLM. Así corre en cualquier servidor con
backend/requirements-simulador.txt (fastapi, uvicorn y python-dotenv).

Preguntas (responder)
---------------------
Hay tres respuestas, armadas a partir de respuestas reales del sistema (corpus v2, prompt
v4, gemma3:4b, 2026-10-05), con el formato de cita que pide el prompt y
fragmentos acortados. Con `etapa` 1, 2 o 7 se devuelve la de esa etapa; con
cualquier otra, o sin etapa, la del plano del servicio (etapa 7). La pregunta
no cambia el texto: el simulador no busca en la guía.

Marcas para probar cada caso (en cualquier parte de la pregunta):
    #no-encontrada     la guía no responde: encontrada=false, confianza null, sin fuentes
    #confianza-media   respuesta con confianza «media»
    #confianza-baja    respuesta con confianza «baja»
    #error             503, como cuando el servidor del LLM no está disponible
Sin marca, la respuesta tiene confianza «alta». SIMULADOR_DEMORA_S agrega una
espera, para probar los tiempos de espera de quien llama (las respuestas reales
tardaron entre 89 y 298 s en un Mac M2 de 8 GB).

Próximos pasos (sugerir)
------------------------
Uno por cada etapa del Propósito 1, armado con los datos de guia.py (objetivo,
actividad y herramientas de la etapa) en el formato de prompts_etapa.py. Las
citas tienen la forma de la línea «fuente:» del corpus («Actividad, p. N» y
«Actividad › Herramienta, p. N»). `contexto` y `datos_etapa` no cambian el
texto; solo se buscan en ellos las mismas marcas.

Adjuntos (cargar_adjunto, borrar_adjunto)
-----------------------------------------
POST /ia/adjuntos valida el archivo de verdad (formato, contenido y tamaño, con
extraer.validar, que no usa Docling) y devuelve un `AdjuntoCargado` fijo: 6
fragmentos, 3 páginas si es PDF y 4 datos personales reemplazados. No lee el
texto. Los ids que entrega quedan en memoria, para que DELETE responda 204 con
uno vigente y 404 con cualquier otro. Marcas en el nombre del archivo:
    #sin-texto         422, como un PDF escaneado
    #error             503, como cuando fallan los modelos

Revisión de entregables (revisar_entregable)
--------------------------------------------
Con un id que entregó cargar_adjunto, devuelve una `Revision` fija armada con la
rúbrica de la herramienta. Los estados, la evidencia y el resumen salen de una
revisión real del perfil de ejemplo (tests/datos/adjuntos/perfil.docx, gemma3:4b,
2026-10-09), acortados. Con cualquier otro id, 404, como un adjunto vencido. El
archivo subido no cambia la respuesta.

Prueba rápida, desde backend/:
    python -m app.rag.simulador "¿Qué es un plano del servicio?"
    python -m app.rag.simulador "¿Cuánto cuesta? #no-encontrada" --etapa 1
    python -m app.rag.simulador --sugerir --etapa 4 --contexto "Licencias médicas #confianza-media"
    python -m app.rag.simulador --adjunto tests/datos/adjuntos/perfil.pdf
    python -m app.rag.simulador --revisar tests/datos/adjuntos/perfil.docx
"""
from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from pathlib import Path

from app.adjuntos.extraer import validar
from app.adjuntos.tipos import NO_DISPONIBLE, AdjuntoCargado, ErrorAdjunto
from app.rag import config, guia
from app.rag.contrato import Fuente, Respuesta
from app.rag.prompts import MENSAJE_NO_ENCONTRADA, SUGERENCIA
from app.rag.prompts_etapa import VERSION_PROMPT_ETAPA
from app.revision import rubricas
from app.revision.prompts import VERSION_PROMPT_REVISION
from app.revision.tipos import NO_EVALUABLE, CriterioRevisado, Revision, texto_revision

# Mejor puntaje del reranker para cada confianza simulada, dentro de los cortes
# por defecto (CONFIANZA_ALTA 0,9 y CONFIANZA_MEDIA 0,7; UMBRAL 0,5).
PUNTAJES = {"alta": 0.95, "media": 0.8, "baja": 0.6}
# Bajo UMBRAL: así queda el mejor puntaje cuando la guía no responde.
PUNTAJE_NO_ENCONTRADA = 0.3


def _fuente(seccion: str, pagina: int, fuente: str, fragmento: str, puntaje: float) -> Fuente:
    return {"seccion": seccion, "pagina": pagina, "fuente": fuente, "fragmento": fragmento, "puntaje": puntaje}


RESPUESTAS = {
    7: ("El plano del servicio es una de las herramientas más utilizadas para implementar iniciativas en el diseño "
        "de servicios. Ayuda a analizar la situación actual y a proyectar la experiencia que se quiere ofrecer, con "
        "un enfoque sistémico que une la perspectiva usuaria y la organizacional "
        "[Modelo operativo › Plano del servicio, p. 122]. Se estructura en capas de información asociadas a las "
        "interacciones: primero se anotan las acciones de las personas usuarias y luego los puntos de contacto en "
        "que ocurren [Modelo operativo › Plano del servicio, p. 122].",
        [_fuente("Plano del servicio", 124, "Modelo operativo › Plano del servicio, p. 124",
                 "CASO DE APLICACIÓN: PLANO DEL SERVICIO\n\n## NUEVO MODELO DE ATENCIÓN FONASA…", 0.936),
         _fuente("Plano del servicio", 122, "Modelo operativo › Plano del servicio, p. 122",
                 "## PLANO DEL SERVICIO\n\n## ¿PARA QUÉ SIRVE?\n\nEsta herramienta es una de las más utilizadas "
                 "para la implementación de iniciativas en el diseño de servicios…", 0.874)]),
    1: ("La guía propone el Plan de investigación de experiencia usuaria, que permite planificar de forma ordenada "
        "y realista una investigación cualitativa centrada en la experiencia "
        "[Investigación › Plan de investigación de experiencia usuaria, p. 110].",
        [_fuente("Plan de investigación de experiencia usuaria", 110,
                 "Investigación › Plan de investigación de experiencia usuaria, p. 110",
                 "## PLAN DE INVESTIGACIÓN DE EXPERIENCIA USUARIA\n\n## ¿PARA QUÉ SIRVE?\n\nEsta herramienta "
                 "permite planificar de forma ordenada y realista una investigación cualitativa…", 0.995),
         _fuente("Investigación", 109, "Investigación, p. 109",
                 "## ¿CUÁNDO DESARROLLARLA?\n\nEsta actividad se lleva a cabo de manera óptima al inicio de un "
                 "proyecto de experiencia…", 0.888)]),
    2: ("El Mapa de perfiles de personas usuarias sirve para explorar y representar la diversidad de grupos de "
        "personas que interactúan con un servicio. Busca identificar patrones y diferencias en su forma de "
        "relacionarse con el servicio para construir una tipología de perfiles; también se puede aplicar a PEC y "
        "personas funcionarias [Personas › Mapa de perfiles de personas usuarias, p. 142].",
        [_fuente("Mapa de perfiles de personas usuarias", 142,
                 "Personas › Mapa de perfiles de personas usuarias, p. 142",
                 "## MAPA DE PERFILES DE PERSONAS USUARIAS\n\n## ¿PARA QUÉ SIRVE?\n\nEsta herramienta les "
                 "permitirá explorar y representar la diversidad de grupos de personas…", 1.0),
         _fuente("Personas", 141, "Personas, p. 141",
                 "## ¿CUÁNDO DESARROLLARLA?\n\nSe recomienda aplicar esta actividad una vez que se dispone de "
                 "hallazgos recogidos a partir de la Investigación…", 0.994)]),
}
ETAPA_POR_DEFECTO = 7


def _caso(marcas: str) -> str:
    """Caso que piden las marcas: «error», «no-encontrada» o la confianza («alta», «media», «baja»)."""
    marcas = marcas.lower()
    if "#error" in marcas:
        raise RuntimeError("Simulador: error pedido con #error. Con los modelos, aquí llega el motivo "
                           "(por ejemplo, que el servidor del LLM no está disponible).")
    if "#no-encontrada" in marcas:
        return "no-encontrada"
    return "media" if "#confianza-media" in marcas else "baja" if "#confianza-baja" in marcas else "alta"


def _esperar() -> float:
    """Espera SIMULADOR_DEMORA_S y devuelve la hora de inicio, para la latencia."""
    t0 = time.time()
    if config.SIMULADOR_DEMORA_S > 0:
        time.sleep(config.SIMULADOR_DEMORA_S)
    return t0


def _con_tope(fuentes: list[dict], puntaje: float) -> list[dict]:
    """Ninguna fuente supera al mejor puntaje, como en una respuesta real."""
    return [{**f, "puntaje": min(f["puntaje"], puntaje)} for f in fuentes]


def responder(pregunta: str, etapa: int | None = None, filtrar_etapa: bool = False) -> Respuesta:
    """
    Respuesta fija con la forma de generar.responder(); la elige `etapa` y la ajustan las marcas.

    `filtrar_etapa` se acepta para tener la misma firma, pero no cambia nada.
    Lanza RuntimeError con la marca #error, como generar.py cuando el LLM no responde.
    """
    t0 = _esperar()
    caso = _caso(pregunta)
    comunes = {"modelo": "simulador", "modo": "simulador"}

    if caso == "no-encontrada":
        return Respuesta(resultado=f"{MENSAJE_NO_ENCONTRADA} {SUGERENCIA}", encontrada=False, confianza=None,
                         puntaje=PUNTAJE_NO_ENCONTRADA, latencia_s=round(time.time() - t0, 1), **comunes)

    puntaje = PUNTAJES[caso]
    texto, fuentes = RESPUESTAS.get(etapa or ETAPA_POR_DEFECTO, RESPUESTAS[ETAPA_POR_DEFECTO])
    return Respuesta(resultado=texto, encontrada=True, confianza=caso, fuentes=_con_tope(fuentes, puntaje),
                     puntaje=puntaje, latencia_s=round(time.time() - t0, 1), **comunes)


def proximos_pasos(etapa: int) -> tuple[str, list[dict]]:
    """
    Texto y fuentes fijos de la etapa, con el formato de prompts_etapa.py.

    Los arma guia.py: el objetivo de la etapa se cita con la página de su
    actividad y cada herramienta con la suya. ValueError si la etapa no existe.
    """
    e = guia.etapa(etapa)
    if e is None:
        raise ValueError(f"La etapa debe ser un número de 1 a {len(guia.PROPOSITOS[1].etapas)}.")
    inicio = e.paginas[0]
    actividad = f"{e.actividad}, p. {inicio}"
    fuentes = [_fuente(e.actividad, inicio, actividad, e.objetivo, 0.99)]
    pasos = [f"- Revisa con tu equipo en qué consiste la actividad de {e.actividad} y cuándo conviene "
             f"desarrollarla [{actividad}]."]
    for i, (pagina, nombre) in enumerate(e.herramientas):
        cita = f"{e.actividad} › {nombre}, p. {pagina}"
        fuentes.append(_fuente(nombre, pagina, cita, f"## {nombre.upper()}\n\n## ¿PARA QUÉ SIRVE?…",
                               round(0.95 - 0.05 * i, 2)))
        pasos.append(f"- Completa la herramienta {nombre} con la información de tu proyecto [{cita}].")
    pasos.append("- Registra en la plataforma lo que ya completaste: así la próxima sugerencia parte desde ahí.")
    herramienta = fuentes[1]
    texto = (f"**Qué busca esta etapa:** {e.objetivo.rstrip('.')} [{actividad}].\n\n"
             "**Próximos pasos:**\n" + "\n".join(pasos) + "\n\n"
             f"**Herramienta sugerida:** {herramienta['seccion']}, la herramienta de la guía para esta "
             f"etapa [{herramienta['fuente']}].")
    return texto, fuentes


def sugerir(etapa: int, contexto: str | dict | None = None, datos_etapa: dict | None = None) -> Respuesta:
    """
    Próximos pasos fijos con la forma de sugerir.sugerir(); los elige `etapa`.

    Las marcas se buscan en `contexto` y `datos_etapa` (en las claves o en los
    valores), que por lo demás no cambian el texto. ValueError si la etapa no
    existe; RuntimeError con la marca #error.
    """
    texto, fuentes = proximos_pasos(etapa)  # valida la etapa antes de esperar
    t0 = _esperar()
    caso = _caso(json.dumps([contexto, datos_etapa], ensure_ascii=False))
    comunes = {"modelo": "simulador", "modo": "simulador", "version_prompt": VERSION_PROMPT_ETAPA}

    if caso == "no-encontrada":
        return Respuesta(resultado=MENSAJE_NO_ENCONTRADA, encontrada=False, confianza=None,
                         puntaje=PUNTAJE_NO_ENCONTRADA, latencia_s=round(time.time() - t0, 1), **comunes)

    puntaje = PUNTAJES[caso]
    return Respuesta(resultado=texto, encontrada=True, confianza=caso, fuentes=_con_tope(fuentes, puntaje),
                     puntaje=puntaje, latencia_s=round(time.time() - t0, 1), **comunes)


_adjuntos: set[str] = set()
_candado = threading.Lock()


def cargar_adjunto(nombre: str, datos: bytes) -> AdjuntoCargado:
    """
    `AdjuntoCargado` fijo para un archivo válido, con un id nuevo.

    Valida como cargar.py (ErrorAdjunto 413, 415 o 422). Con #sin-texto en el
    nombre, 422; con #error, RuntimeError (503).
    """
    t0 = _esperar()
    formato = validar(nombre, datos)
    if "#error" in nombre.lower():
        raise RuntimeError("Simulador: error pedido con #error. Con los modelos, aquí llega el motivo "
                           "(por ejemplo, que no hay memoria para cargar bge-m3).")
    if "#sin-texto" in nombre.lower():
        raise ErrorAdjunto("El PDF parece escaneado: no tiene texto que pueda leer. Súbelo como DOCX o como PDF "
                           "exportado desde el editor de texto.")
    adjunto_id = secrets.token_urlsafe(16)
    with _candado:
        _adjuntos.add(adjunto_id)
    return AdjuntoCargado(adjunto_id=adjunto_id, nombre=nombre, formato=formato,
                          paginas=3 if formato == "pdf" else None, fragmentos=6, caracteres=4200,
                          reemplazos={"RUT": 2, "CORREO": 1, "TELEFONO": 1},
                          expira_en_s=int(config.MINUTOS_ADJUNTO * 60), modo="simulador",
                          latencia_s=round(time.time() - t0, 1))


def borrar_adjunto(adjunto_id: str) -> bool:
    """True si el id lo entregó cargar_adjunto y no se había borrado."""
    with _candado:
        if adjunto_id not in _adjuntos:
            return False
        _adjuntos.remove(adjunto_id)
        return True


def adjuntos_vigentes() -> int:
    with _candado:
        return len(_adjuntos)


# De una revisión real del perfil de ejemplo (gemma3:4b, 2026-10-09), acortada: id → (estado, evidencia, falta).
REVISION_PERFIL = {
    "rol": ("parcial", "conductora de 68 años que renueva su licencia cada tres años y vive en un sector rural.",
            "No dice cuánta influencia tiene sobre el resultado del servicio."),
    "necesidades": ("cumple", "saber qué documentos llevar antes de viajar a la municipalidad y poder pedir hora "
                              "sin usar internet.", ""),
    "expectativas": ("cumple", "Expectativas del resultado: salir con la licencia renovada en una sola visita.", ""),
    "relacion": ("parcial", "llama por teléfono, pero nadie contesta en la tarde",
                 "No dice si el uso es voluntario u obligatorio ni qué tan crítico es su objetivo."),
    "variables": ("no_cumple", "", ""),
    "otras_caracteristicas": ("cumple", "vive en un sector rural", ""),
    "nombre": ("no_cumple", "", ""),
    "origen": ("cumple", "Se entrevistó a 12 personas entre agosto y septiembre de 2026.", ""),
    "validacion": ("no_cumple", "", ""),
    "cantidad": ("cumple", "El documento describe un perfil: «Perfil: persona mayor que renueva su licencia».", ""),
    "representacion": ("no_cumple", "", ""),
}
RESUMEN_PERFIL = ("Perfil de una conductora de 68 años de un sector rural que renueva su licencia cada tres años. "
                  "Necesita saber qué documentos llevar y pedir hora sin internet, y espera renovarla en una sola "
                  "visita. Hoy llama por teléfono, pero nadie contesta en la tarde.")


def revisar_entregable(adjunto_id: str, herramienta: str = "perfil_persona_usuaria") -> Revision:
    """
    `Revision` fija con la forma de revisar.revisar(), armada con la rúbrica de `herramienta`.

    ErrorAdjunto(404) si cargar_adjunto no entregó `adjunto_id`; KeyError si la
    herramienta no tiene rúbrica. Un criterio que no está en REVISION_PERFIL queda «no_cumple».
    """
    rubrica = rubricas.cargar(herramienta)
    t0 = _esperar()
    with _candado:
        if adjunto_id not in _adjuntos:
            raise ErrorAdjunto(NO_DISPONIBLE, 404)
    criterios = []
    for c in rubrica.criterios:
        estado, evidencia, falta = REVISION_PERFIL.get(c.id, ("no_cumple", "", ""))
        sugerencia = {"cumple": "", "no_evaluable": NO_EVALUABLE}.get(estado, f"{falta} {c.sugerencia}".strip())
        criterios.append(CriterioRevisado(id=c.id, nombre=c.nombre, tipo=c.tipo, estado=estado, evidencia=evidencia,
                                          sugerencia=sugerencia, pagina=c.pagina, cita=c.cita(),
                                          revisado_con=c.revisa))
    obligatorios = [c for c in criterios if c.tipo == "obligatorio"]
    return Revision(herramienta=rubrica.id, nombre=rubrica.nombre, fuente=rubrica.fuente,
                    version_rubrica=rubrica.version, rubrica_validada=rubrica.validada, resumen=RESUMEN_PERFIL,
                    criterios=criterios, obligatorios=len(obligatorios),
                    obligatorios_cumplidos=sum(c.estado == "cumple" for c in obligatorios),
                    resultado=texto_revision(rubrica.nombre, rubrica.fuente, RESUMEN_PERFIL, criterios),
                    modelo="simulador", version_prompt=VERSION_PROMPT_REVISION, modo="simulador",
                    latencia_s=round(time.time() - t0, 1), llamadas_llm=0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta", nargs="?", default="", help="pregunta, con las marcas que quieras probar")
    ap.add_argument("--etapa", type=int, help="etapa del proyecto (1-7): elige la respuesta fija")
    ap.add_argument("--sugerir", action="store_true", help="próximos pasos de --etapa, como sugerir.py")
    ap.add_argument("--contexto", help="contexto del proyecto, con --sugerir (aquí van las marcas)")
    ap.add_argument("--adjunto", type=Path, help="archivo a «subir», como POST /ia/adjuntos")
    ap.add_argument("--revisar", type=Path, help="archivo a «subir» y revisar, como POST /ia/revisar-entregable")
    args = ap.parse_args()
    if args.revisar:
        adjunto = cargar_adjunto(args.revisar.name, args.revisar.read_bytes())
        print(revisar_entregable(adjunto.adjunto_id).resultado)
        return
    if args.adjunto:
        print(json.dumps(cargar_adjunto(args.adjunto.name, args.adjunto.read_bytes()).a_dict(),
                         ensure_ascii=False, indent=2))
        return
    if args.sugerir:
        if args.etapa is None:
            ap.error("--sugerir necesita --etapa.")
        r = sugerir(args.etapa, args.contexto)
    elif not args.pregunta:
        ap.error("Falta la pregunta (o usa --sugerir --etapa N).")
    else:
        r = responder(args.pregunta, args.etapa)
    print(json.dumps(r.a_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
