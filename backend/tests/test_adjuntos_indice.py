"""Índice en memoria de los adjuntos, con embeddings y reranker de prueba (sin modelos)."""
from __future__ import annotations

import pytest
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import MetadataMode, NodeWithScore

from app.adjuntos import indice
from app.adjuntos.tipos import ArchivoExtraido, ErrorAdjunto, Seccion
from app.rag import config


class ReordenadorPorPalabras:
    """Puntúa cada fragmento por la fracción de palabras de la consulta que contiene."""

    def reordenar(self, nodos: list[NodeWithScore], consulta: str, top_n: int) -> list[NodeWithScore]:
        palabras = set(consulta.lower().split())
        for n in nodos:
            texto = n.node.get_content(metadata_mode=MetadataMode.EMBED).lower()
            n.score = sum(p in texto for p in palabras) / len(palabras)
        return sorted(nodos, key=lambda n: n.score, reverse=True)[:top_n]


class Reloj:
    def __init__(self) -> None:
        self.ahora = 1000.0

    def __call__(self) -> float:
        return self.ahora


@pytest.fixture(autouse=True)
def sin_modelos(monkeypatch: pytest.MonkeyPatch) -> Reloj:
    reloj = Reloj()
    monkeypatch.setattr(indice, "embedding", lambda: MockEmbedding(embed_dim=8))
    monkeypatch.setattr(indice, "reordenador", lambda: ReordenadorPorPalabras())
    monkeypatch.setattr(indice, "reloj", reloj)
    monkeypatch.setattr(indice, "_adjuntos", {})
    monkeypatch.setattr(config, "MINUTOS_ADJUNTO", 60.0)
    monkeypatch.setattr(config, "MAX_ADJUNTOS", 5)
    return reloj


def _archivo(*secciones: Seccion, nombre: str = "Perfil Paula Rojas.pdf", paginas: int | None = 2) -> ArchivoExtraido:
    return ArchivoExtraido(nombre=nombre, formato="pdf", secciones=list(secciones), paginas=paginas)


PDF = _archivo(Seccion("La persona usuaria necesita saber qué documentos llevar.", pagina=1, titulo="Perfil"),
               Seccion("Las dudas se envían a la encargada, RUT [RUT_1].", pagina=2))


def test_indexar_devuelve_el_resumen() -> None:
    adjunto = indice.indexar(PDF, {"[RUT_1]": "12.345.678-5"}, {"RUT": 1})

    assert adjunto.fragmentos == 2
    assert adjunto.paginas == 2
    assert adjunto.caracteres == PDF.caracteres()
    assert adjunto.reemplazos == {"RUT": 1}
    assert adjunto.expira_en_s == 3600
    assert adjunto.nombre == "Perfil Paula Rojas.pdf"
    assert len(adjunto.adjunto_id) >= 20
    assert indice.vigentes() == 1


@pytest.mark.parametrize("seccion, fuente, pagina, nombre_seccion", [
    (Seccion("Texto.", pagina=3, titulo="Perfil"), "Adjunto, p. 3", 3, "Perfil"),
    (Seccion("Texto.", titulo="Seguimiento"), "Adjunto › Seguimiento", 0, "Seguimiento"),
    (Seccion("Texto."), "Adjunto", 0, "Adjunto"),
])
def test_metadatos_y_fuente(seccion: Seccion, fuente: str, pagina: int, nombre_seccion: str) -> None:
    adjunto = indice.indexar(_archivo(seccion), {}, {})
    [n] = indice.buscar(adjunto.adjunto_id, "texto")
    m = n.node.metadata

    assert m["fuente"] == fuente
    assert (m["origen"], m["adjunto_id"]) == ("adjunto", adjunto.adjunto_id)
    assert m["pagina_inicio"] == m["pagina_fin"] == pagina
    assert m["seccion"] == nombre_seccion
    # Solo la fuente entra al texto que ve el LLM, y nunca el nombre del archivo.
    assert n.node.get_content(metadata_mode=MetadataMode.LLM) == f"fuente: {fuente}\n\nTexto."
    assert "Paula" not in str(m)


def test_secciones_vacias_no_generan_fragmentos() -> None:
    adjunto = indice.indexar(_archivo(Seccion("   "), Seccion("Algo de texto.", pagina=2)), {}, {})

    assert adjunto.fragmentos == 1


def test_sin_texto_es_un_error() -> None:
    with pytest.raises(ErrorAdjunto) as e:
        indice.indexar(_archivo(Seccion("  \n ")), {}, {})
    assert e.value.estado == 422


def test_secciones_largas_se_dividen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CHUNK_TOKENS", 60)
    monkeypatch.setattr(config, "CHUNK_OVERLAP", 10)
    largo = " ".join(f"Oración número {i} del documento de prueba." for i in range(60))

    assert indice.indexar(_archivo(Seccion(largo, pagina=1)), {}, {}).fragmentos > 3


def test_buscar_ordena_y_respeta_top_k() -> None:
    adjunto = indice.indexar(PDF, {}, {})
    nodos = indice.buscar(adjunto.adjunto_id, "dudas encargada", top_k=1)

    assert len(nodos) == 1
    assert nodos[0].node.metadata["fuente"] == "Adjunto, p. 2"
    assert nodos[0].score == 1.0


def test_dos_adjuntos_no_se_mezclan() -> None:
    a = indice.indexar(PDF, {}, {})
    b = indice.indexar(_archivo(Seccion("Otro documento sobre trámites municipales.", pagina=1)), {}, {})

    assert {n.node.metadata["adjunto_id"] for n in indice.buscar(a.adjunto_id, "documento", top_k=10)} == {
        a.adjunto_id}
    assert {n.node.metadata["adjunto_id"] for n in indice.buscar(b.adjunto_id, "documento", top_k=10)} == {
        b.adjunto_id}


def test_adjunto_inexistente() -> None:
    with pytest.raises(ErrorAdjunto) as e:
        indice.buscar("no-existe", "hola")
    assert e.value.estado == 404
    assert "vuelve a subirlo" in e.value.mensaje


def test_vence(sin_modelos: Reloj) -> None:
    adjunto = indice.indexar(PDF, {"[RUT_1]": "12.345.678-5"}, {"RUT": 1})
    sin_modelos.ahora += 59 * 60
    assert indice.correspondencias(adjunto.adjunto_id) == {"[RUT_1]": "12.345.678-5"}

    sin_modelos.ahora += 2 * 60
    assert indice.vigentes() == 0
    with pytest.raises(ErrorAdjunto) as e:
        indice.correspondencias(adjunto.adjunto_id)
    assert e.value.estado == 404


def test_tope_descarta_el_mas_antiguo(sin_modelos: Reloj, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "MAX_ADJUNTOS", 2)
    ids = []
    for _ in range(3):
        ids.append(indice.indexar(PDF, {}, {}).adjunto_id)
        sin_modelos.ahora += 1

    assert indice.vigentes() == 2
    with pytest.raises(ErrorAdjunto):
        indice.buscar(ids[0], "dudas")
    assert indice.buscar(ids[2], "dudas")


def test_borrar() -> None:
    adjunto = indice.indexar(PDF, {}, {})

    assert indice.borrar(adjunto.adjunto_id) is True
    assert indice.borrar(adjunto.adjunto_id) is False
    assert indice.vigentes() == 0


def test_correspondencias_es_una_copia() -> None:
    adjunto = indice.indexar(PDF, {"[RUT_1]": "12.345.678-5"}, {})
    indice.correspondencias(adjunto.adjunto_id).clear()

    assert indice.correspondencias(adjunto.adjunto_id) == {"[RUT_1]": "12.345.678-5"}
