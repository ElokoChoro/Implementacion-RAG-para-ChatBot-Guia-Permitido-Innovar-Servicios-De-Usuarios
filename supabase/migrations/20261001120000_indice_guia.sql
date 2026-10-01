-- Índice vectorial de la guía, en el formato de PGVectorStore (LlamaIndex).
--
-- PGVectorStore antepone «data_» al nombre que recibe: con TABLA_PGVECTOR=guia_fragmentos
-- (backend/app/rag/config.py) lee y escribe en public.data_guia_fragmentos. Las columnas
-- son las que espera la librería; el backend la abre con perform_setup=False, así que
-- esta migración es la única que crea la tabla.
--
-- La dimensión es la de BAAI/bge-m3 (1024). Si cambia el modelo de embeddings, hace
-- falta una migración nueva con la dimensión del modelo y volver a indexar.

create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table public.data_guia_fragmentos (
  id        bigserial primary key,
  text      varchar not null,              -- texto del fragmento
  metadata_ jsonb,                         -- fuente, seccion, actividad, herramienta, etapa, páginas, versión…
  node_id   varchar,                       -- id del nodo de LlamaIndex
  embedding extensions.vector(1024)        -- bge-m3, normalizado
);

comment on table public.data_guia_fragmentos is
  'Fragmentos de la guía con su embedding (bge-m3, 1024). Se recarga completa con python -m ingesta.indexar.';

-- Búsqueda por similitud coseno (PGVectorStore ordena por embedding <=> pregunta).
create index data_guia_fragmentos_embedding_idx
  on public.data_guia_fragmentos
  using hnsw (embedding extensions.vector_cosine_ops);

-- PGVectorStore borra por documento de origen (ref_doc_id) al reindexar una página.
create index data_guia_fragmentos_ref_doc_id_idx
  on public.data_guia_fragmentos ((metadata_ ->> 'ref_doc_id'));

-- Filtro por etapa de la plataforma (recuperar --etapa N).
create index data_guia_fragmentos_etapa_idx
  on public.data_guia_fragmentos (((metadata_ ->> 'etapa')::float));

-- La tabla solo se usa desde el backend, con la conexión directa a Postgres (rol
-- postgres, que no pasa por RLS). Con RLS activo y sin políticas, la API pública de
-- Supabase (claves anon y authenticated) no puede leerla ni escribirla.
alter table public.data_guia_fragmentos enable row level security;
