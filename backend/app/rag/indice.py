"""
Índice vectorial de la guía.

Los fragmentos y sus vectores se guardan, con distancia coseno, en el vector
store que indica config.ALMACEN:

  chroma    en disco (config.RUTA_CHROMA), una colección por configuración
  pgvector  en Supabase (config.SUPABASE_DB_URL), en una tabla creada por la
            migración de supabase/migrations/

El índice se carga con `python -m ingesta.indexar`; este módulo solo lo abre.
"""
from __future__ import annotations

from functools import lru_cache

from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores.types import BasePydanticVectorStore

from app.rag import config
from app.rag.modelos import embedding

ALMACENES = ("chroma", "pgvector")


def _chroma(reiniciar: bool):
    import chromadb
    from llama_index.vector_stores.chroma import ChromaVectorStore

    cliente = chromadb.PersistentClient(path=str(config.RUTA_CHROMA))
    if reiniciar and config.coleccion() in [c.name for c in cliente.list_collections()]:
        cliente.delete_collection(config.coleccion())
    col = cliente.get_or_create_collection(config.coleccion(), metadata={"hnsw:space": "cosine"})
    return ChromaVectorStore(chroma_collection=col)


def tabla_pgvector() -> str:
    """Nombre real de la tabla en Postgres (PGVectorStore le antepone «data_»)."""
    return f"data_{config.TABLA_PGVECTOR.lower()}"


@lru_cache(maxsize=1)
def _motor():
    """Motor de SQLAlchemy para revisar la tabla (PGVectorStore abre los suyos)."""
    import sqlalchemy

    if not config.SUPABASE_DB_URL:
        raise RuntimeError("Falta SUPABASE_DB_URL. Cópiala en .env desde el panel de Supabase "
                           "(Project Settings › Database › Connection string, Session pooler).")
    url = sqlalchemy.make_url(config.SUPABASE_DB_URL).set(drivername="postgresql+psycopg2")
    return sqlalchemy.create_engine(url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _pgvector_abierto():
    """
    PGVectorStore de la tabla del índice. Se abre una sola vez por proceso:
    cada uno crea sus propios pools de conexiones, y el pooler de Supabase admite
    pocas conexiones en el plan gratuito.
    """
    import sqlalchemy
    from llama_index.vector_stores.postgres import PGVectorStore

    with _motor().connect() as con:
        existe = con.execute(sqlalchemy.text("select to_regclass(:t)"),
                             {"t": f"public.{tabla_pgvector()}"}).scalar()
    if not existe:
        raise RuntimeError(f"No existe la tabla public.{tabla_pgvector()} en Supabase. Aplica "
                           "las migraciones de supabase/migrations/ (ver README).")
    url = sqlalchemy.make_url(config.SUPABASE_DB_URL)

    def con_driver(driver: str) -> str:
        return url.set(drivername=driver).render_as_string(hide_password=False)

    return PGVectorStore.from_params(
        connection_string=con_driver("postgresql+psycopg2"),
        # La librería lo pide, pero el índice solo se usa con llamadas síncronas
        async_connection_string=con_driver("postgresql+asyncpg"),
        table_name=config.TABLA_PGVECTOR,
        embed_dim=config.EMBEDDINGS_DIM,
        use_jsonb=True,
        # La tabla y sus índices los crea la migración, no la librería
        perform_setup=False,
    )


def _pgvector(reiniciar: bool):
    vs = _pgvector_abierto()
    if reiniciar:
        vs.clear()
    return vs


def vector_store(reiniciar: bool = False) -> BasePydanticVectorStore:
    """
    Abre el vector store de config.ALMACEN.

    Con `reiniciar=True` lo vacía antes, para indexar desde cero.
    """
    if config.ALMACEN == "chroma":
        return _chroma(reiniciar)
    if config.ALMACEN == "pgvector":
        return _pgvector(reiniciar)
    raise ValueError(f"ALMACEN={config.ALMACEN!r} no es válido; usa uno de {ALMACENES}")


def descripcion() -> str:
    """Dónde está el índice, para los mensajes de la ingesta y de las pruebas."""
    if config.ALMACEN == "pgvector":
        return f"pgvector, tabla public.{tabla_pgvector()}"
    return f"Chroma, colección «{config.coleccion()}» en {config.RUTA_CHROMA}"


def contar(vs: BasePydanticVectorStore) -> int:
    """Número de fragmentos guardados."""
    if config.ALMACEN == "pgvector":
        import sqlalchemy

        with _motor().connect() as con:
            return con.execute(sqlalchemy.text(f'select count(*) from public."{tabla_pgvector()}"')).scalar()
    return vs._collection.count()


def _configuracion_indexada() -> str | None:
    """Configuración (`config.coleccion()`) con que se cargó la tabla de pgvector."""
    import sqlalchemy

    with _motor().connect() as con:
        return con.execute(sqlalchemy.text(
            f"select metadata_ ->> 'indice' from public.\"{tabla_pgvector()}\" limit 1")).scalar()


def indice() -> VectorStoreIndex:
    """
    Índice de LlamaIndex sobre el vector store ya cargado, con el modelo de
    embeddings que vectoriza las preguntas.

    Lanza RuntimeError si está vacío (todavía no se indexó) o si la tabla de
    pgvector se cargó con otro corpus, modelo o fragmentación.
    """
    vs = vector_store()
    if contar(vs) == 0:
        raise RuntimeError(f"El índice ({descripcion()}) está vacío. "
                           f"Ejecuta desde la raíz:  ALMACEN={config.ALMACEN} python -m ingesta.indexar")
    if config.ALMACEN == "pgvector" and (cargada := _configuracion_indexada()) != config.coleccion():
        raise RuntimeError(f"La tabla public.{tabla_pgvector()} tiene el índice «{cargada}», pero la "
                           f"configuración actual es «{config.coleccion()}». Vuelve a indexar: "
                           "ALMACEN=pgvector python -m ingesta.indexar")
    return VectorStoreIndex.from_vector_store(vs, embed_model=embedding())
