"""
Índice en memoria de cada adjunto, separado del de la guía y con vencimiento.

indexar() divide cada sección del adjunto (ya seudonimizado) con el mismo
SentenceSplitter que la guía (CHUNK_TOKENS, CHUNK_OVERLAP) y la vectoriza con
bge-m3 (`embedding()`, la misma instancia que usa la guía) en un
VectorStoreIndex en memoria. buscar() recupera RERANKER_CANDIDATOS por
similitud y los reordena con el reranker, como recuperar.py: así los puntajes
se pueden comparar con UMBRAL.

Por qué en memoria: el adjunto trae datos de personas. No va a Chroma en disco
ni a pgvector en Supabase, y se borra solo a los MINUTOS_ADJUNTO. Un entregable
tiene unas decenas de fragmentos, así que buscar en memoria es instantáneo. Se
guardan a lo más MAX_ADJUNTOS: al subir uno más se descarta el más antiguo. Si
la API se reinicia, los adjuntos se pierden y hay que volver a subirlos.

Cada adjunto guarda también la tabla de correspondencias (marcador → valor
real) de seudonimizar.py, que nunca entra al índice ni al texto de los fragmentos.

El `adjunto_id` sale de secrets.token_urlsafe: no se puede adivinar el de otra persona.

Prueba rápida, desde backend/ (carga Docling, bge-m3 y el reranker):
    python -m app.adjuntos.indice tests/datos/adjuntos/perfil.docx "¿Qué necesita la persona usuaria?"
"""
from __future__ import annotations

import argparse
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeWithScore

from app.adjuntos.tipos import NO_DISPONIBLE, AdjuntoCargado, ArchivoExtraido, ErrorAdjunto, Seccion
from app.rag import config
from app.rag.modelos import embedding, reordenador


@dataclass
class _Entrada:
    indice: VectorStoreIndex
    adjunto: AdjuntoCargado
    correspondencias: dict[str, str]
    creado: float
    vence: float


_adjuntos: dict[str, _Entrada] = {}
_candado = threading.Lock()
# Reloj de los vencimientos; los tests lo reemplazan para no esperar.
reloj: Callable[[], float] = time.monotonic


def fuente(seccion: Seccion) -> str:
    """Cita de una sección del adjunto. Sin el nombre del archivo, que puede traer nombres de personas."""
    if seccion.pagina:
        return f"Adjunto, p. {seccion.pagina}"
    if seccion.titulo:
        return f"Adjunto › {seccion.titulo}"
    return "Adjunto"


def _documentos(adjunto_id: str, archivo: ArchivoExtraido) -> list[Document]:
    docs = []
    for seccion in archivo.secciones:
        if not seccion.texto.strip():
            continue
        meta = {
            "origen": "adjunto",
            "adjunto_id": adjunto_id,
            "seccion": seccion.titulo or "Adjunto",
            "pagina_inicio": seccion.pagina or 0,  # 0 = sin página (DOCX, MD)
            "pagina_fin": seccion.pagina or 0,
            "fuente": fuente(seccion),
        }
        ocultas = [k for k in meta if k != "fuente"]
        # Como en la guía (ingesta/indexar.py): solo «fuente» entra al texto que se vectoriza,
        # al que lee el reranker y al que ve el LLM.
        docs.append(Document(text=seccion.texto, metadata=meta,
                             excluded_embed_metadata_keys=ocultas, excluded_llm_metadata_keys=ocultas))
    return docs


def _limpiar_vencidos(ahora: float) -> None:
    """Borra los adjuntos vencidos. Se llama con el candado tomado."""
    for adjunto_id in [i for i, e in _adjuntos.items() if e.vence <= ahora]:
        del _adjuntos[adjunto_id]


def indexar(archivo: ArchivoExtraido, correspondencias: dict[str, str],
            reemplazos: dict[str, int]) -> AdjuntoCargado:
    """
    Fragmenta, vectoriza y guarda en memoria `archivo`, que ya viene seudonimizado.

    Devuelve el `AdjuntoCargado` sin latencia: la completa quien llama.
    """
    adjunto_id = secrets.token_urlsafe(16)
    splitter = SentenceSplitter(chunk_size=config.CHUNK_TOKENS, chunk_overlap=config.CHUNK_OVERLAP)
    nodos = splitter.get_nodes_from_documents(_documentos(adjunto_id, archivo))
    if not nodos:
        raise ErrorAdjunto("El documento no tiene texto que pueda leer. Revisa que sea el correcto y vuelve "
                           "a subirlo.")
    indice = VectorStoreIndex(nodos, embed_model=embedding())  # SimpleVectorStore, en memoria
    duracion = config.MINUTOS_ADJUNTO * 60
    adjunto = AdjuntoCargado(adjunto_id=adjunto_id, nombre=archivo.nombre, formato=archivo.formato,
                             paginas=archivo.paginas, fragmentos=len(nodos), caracteres=archivo.caracteres(),
                             reemplazos=dict(reemplazos), expira_en_s=int(duracion))
    with _candado:
        ahora = reloj()
        _limpiar_vencidos(ahora)
        while len(_adjuntos) >= config.MAX_ADJUNTOS:
            del _adjuntos[min(_adjuntos, key=lambda i: _adjuntos[i].creado)]
        _adjuntos[adjunto_id] = _Entrada(indice=indice, adjunto=adjunto, correspondencias=dict(correspondencias),
                                         creado=ahora, vence=ahora + duracion)
    return adjunto


def _entrada(adjunto_id: str) -> _Entrada:
    with _candado:
        _limpiar_vencidos(reloj())
        entrada = _adjuntos.get(adjunto_id)
    if entrada is None:
        raise ErrorAdjunto(NO_DISPONIBLE, 404)
    return entrada


def buscar(adjunto_id: str, consulta: str, top_k: int = config.TOP_K) -> list[NodeWithScore]:
    """
    Fragmentos del adjunto más relevantes para `consulta`, del mejor al peor, con el
    puntaje del reranker (0 a 1). ErrorAdjunto(404) si no existe o venció.
    """
    retriever = _entrada(adjunto_id).indice.as_retriever(
        similarity_top_k=max(config.RERANKER_CANDIDATOS, top_k))
    return reordenador().reordenar(retriever.retrieve(consulta), consulta, top_k)


def correspondencias(adjunto_id: str) -> dict[str, str]:
    """Tabla marcador → valor real del adjunto. ErrorAdjunto(404) si no existe o venció."""
    return dict(_entrada(adjunto_id).correspondencias)


def borrar(adjunto_id: str) -> bool:
    """Quita el adjunto de la memoria. False si no existía o ya había vencido."""
    with _candado:
        _limpiar_vencidos(reloj())
        return _adjuntos.pop(adjunto_id, None) is not None


def vigentes() -> int:
    """Adjuntos en memoria que no han vencido."""
    with _candado:
        _limpiar_vencidos(reloj())
        return len(_adjuntos)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archivo", help="adjunto de prueba (PDF, DOCX o MD)")
    ap.add_argument("consulta")
    ap.add_argument("-k", type=int, default=config.TOP_K, help="fragmentos a devolver")
    args = ap.parse_args()

    from pathlib import Path

    # Con «python -m», este archivo corre como __main__: el registro de adjuntos que llena
    # cargar_adjunto es el del módulo app.adjuntos.indice, así que se busca en ese.
    from app.adjuntos import indice
    from app.adjuntos.cargar import cargar_adjunto

    ruta = Path(args.archivo)
    adjunto = cargar_adjunto(ruta.name, ruta.read_bytes())
    print(f"{adjunto.fragmentos} fragmentos, {adjunto.reemplazos or 'sin'} datos reemplazados, "
          f"indexado en {adjunto.latencia_s} s\n")
    t0 = time.time()
    nodos = indice.buscar(adjunto.adjunto_id, args.consulta, args.k)
    print(f"{len(nodos)} fragmentos en {time.time() - t0:.1f} s\n")
    for i, n in enumerate(nodos, 1):
        print(f"{i}. [{n.score:.3f}] {n.node.metadata['fuente']}\n   {n.node.get_content()[:220]}…\n")


if __name__ == "__main__":
    main()
