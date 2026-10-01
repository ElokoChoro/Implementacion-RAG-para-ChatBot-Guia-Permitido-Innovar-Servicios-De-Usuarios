# Módulo RAG · Permitido Innovar

Asistente que responde preguntas usando solo la guía «¿Cómo podemos innovar en los servicios públicos
desde la experiencia usuaria?», cita la sección y página de origen y funciona con modelos locales.

| Carpeta | Contenido |
| --- | --- |
| `src/` | Interfaz de chat de demo (React + Vite), conectada a la API |
| `backend/app/api.py` | API HTTP (FastAPI): `POST /ia/consultar-guia` |
| `backend/app/rag/` | Modelos, índice y recuperación del RAG |
| `ingesta/` | Extraer la guía → corpus con metadatos → índice vectorial |
| `data/corpus/` | Corpus extraído y versionado ([README](data/corpus/README.md)) |
| `data/fuentes/` | Manifiesto del PDF (el PDF no se versiona) |
| `eval/` | Set de preguntas y comparaciones de recuperación ([README](eval/README.md)) |
| `supabase/migrations/` | Esquema de la base en Supabase: tabla del índice con pgvector |

## Pipeline

```text
PDF ──Docling standard, sin OCR──▶ JSON ──▶ paginas.jsonl ──SentenceSplitter 400/50──▶ fragmentos
                                                                                      │ bge-m3 (FlagEmbedding)
pregunta ──bge-m3──▶ top 20 por coseno en el índice ──bge-reranker-v2-m3──▶ top 4 ◀───┘
                                                                               │ umbral
                             «No encuentro esa información en la guía.» ◀──no──┤ ¿algún fragmento ≥ UMBRAL?
                                                                               │ sí
                             respuesta con citas y confianza ◀──gemma3:4b (Ollama)
```

| Pieza | Elección | Configuración (`backend/app/rag/config.py`) |
| --- | --- | --- |
| Extracción | Docling 2.131, pipeline `standard`, sin OCR | — |
| Corpus | `v2`, una página por bloque: créditos (p. 2), prólogos (8–11) y págs. 13–163 | `VERSION_CORPUS` |
| Fragmentos | `SentenceSplitter` de LlamaIndex, 400 tokens, solapamiento 50 | `CHUNK_TOKENS`, `CHUNK_OVERLAP` |
| Embeddings | `BAAI/bge-m3` con FlagEmbedding, densos, 1024 dimensiones | `EMBEDDINGS` |
| Vector store | Chroma local o pgvector en Supabase, distancia coseno | `ALMACEN`, `RUTA_CHROMA`, `SUPABASE_DB_URL` |
| Reranker | `BAAI/bge-reranker-v2-m3` con FlagEmbedding, puntaje 0–1 | `RERANKER`, `RERANKER_CANDIDATOS`, `TOP_K`, `USAR_RERANKER` |
| Umbral | Puntaje del reranker ≥ 0,5; si ningún fragmento llega, se rechaza sin LLM | `UMBRAL` |
| LLM | `gemma3:4b` en Ollama, temperature 0,1, contexto de 4096 tokens | `LLM`, `TEMPERATURE`, `CONTEXTO_TOKENS`, `MAX_TOKENS_RESPUESTA` |
| Confianza | Mejor puntaje del reranker: alta ≥ 0,9, media ≥ 0,7, baja el resto | `CONFIANZA_ALTA`, `CONFIANZA_MEDIA` |
| Hardware | `mps`, `cuda:0` o `cpu`; fp16 por defecto | `DISPOSITIVO`, `FP16` |

## Decisiones de diseño

- **Docling `standard`, sin OCR.** Toma el texto de la capa de texto del PDF y un modelo de layout
  ordena las columnas y registra la página de cada bloque, que se usa para citar. El pipeline VLM de
  Docling, que lee cada página como imagen, se descartó: sobre esta guía inventa palabras (~6 % no
  existen en el PDF), tarda ~40 min y no guarda la página de cada bloque. El texto que está dentro de
  las láminas y fichas se incluye como párrafo `[Figura] …`.
- **Una página por registro en el corpus.** Cada página lleva sección, actividad, herramienta y etapa,
  para citar «sección, p. N» y filtrar por etapa.
- **Créditos, prólogos y elaboración en el índice.** El corpus `v1` empezaba en la Introducción, así
  que el asistente no podía decir quién hizo la guía, cuándo ni con qué licencia. Desde `v2` también
  entran los créditos (p. 2), los prólogos (8–11) y «¿Cómo elaboramos esta guía?» (162–163). Quedan
  fuera la portada, los índices, las referencias y la contraportada.
- **bge-m3 + reranker.** bge-m3 es multilingüe, corre local y tiene licencia MIT. Comparado con
  qwen3-embedding:0.6b y embeddinggemma sobre el set de evaluación, los tres empatan (recall@4 de
  95,7 %). El reranker sube la recuperación a 97,9 % y ordena mejor los fragmentos (MRR de 0,906 a
  0,952), a cambio de ~5 s por pregunta. Detalle en [eval/README.md](eval/README.md).
- **Umbral antes del LLM y confianza desde el reranker.** Si ningún fragmento supera el umbral, la
  guía no responde la pregunta y se contesta «No encuentro esa información en la guía.» sin llamar al
  LLM: no hay contexto del que pueda inventar. El LLM todavía puede rechazar si los fragmentos no
  responden; el prompt lo obliga a empezar con esa frase. La confianza (alta, media o baja) y las
  fuentes salen del reranker y de los fragmentos, no del texto del LLM, así que no dependen de que un
  modelo de 4B las escriba bien. Calibración en [eval/README.md](eval/README.md#umbral-de-rechazo).
- **Todo corre en local.** Los modelos se descargan una vez desde Hugging Face y después funcionan sin
  red; ni la guía ni las preguntas salen del equipo.
- **El corpus se versiona y el PDF no.** El índice se reconstruye desde el corpus con un comando; el
  PDF se identifica por su hash en `data/fuentes/guia.yaml`.

## Instalación (Python 3.12)

```bash
python3.12 -m venv .venv
```

```bash
.venv/bin/pip install -r ingesta/requirements.txt
```

La consulta sola (sin Docling) necesita únicamente `backend/requirements.txt`. La primera ejecución
descarga los modelos desde Hugging Face (bge-m3 ~2,3 GB, reranker ~2,3 GB); después corren sin red.

La generación necesita [Ollama](https://ollama.com/download) corriendo con el LLM (~3,3 GB):

```bash
ollama pull gemma3:4b
```

## Reconstruir el índice

El corpus `v2` ya está en el repositorio, así que basta con indexar:

```bash
.venv/bin/python -m ingesta.indexar
```

Para regenerar el corpus desde el PDF (por ejemplo, si cambia la guía o la versión de Docling):

```bash
.venv/bin/python -m ingesta.extraer "/ruta/a/Guia_ComoInnovar.pdf"
```

```bash
.venv/bin/python -m ingesta.corpus
```

`ingesta.extraer` compara el hash del PDF con `data/fuentes/guia.yaml`. `ingesta.corpus --ver 148`
muestra cómo quedó una página.

## Índice en Supabase (pgvector)

Con `ALMACEN=pgvector` el índice vive en Supabase, en la tabla `public.data_guia_fragmentos`
(`vector(1024)`, índice HNSW por coseno y RLS sin políticas, así que la API pública no la lee). Los
embeddings se siguen calculando en local; a Supabase solo llegan los vectores, el texto y los metadatos.

1. Copia `.env.example` como `.env` y completa `SUPABASE_DB_URL` con el connection string del
   *Session pooler* (Project Settings › Database › Connection string) y la contraseña de la base.
2. Aplica la migración, con la [CLI de Supabase](https://supabase.com/docs/guides/cli):

   ```bash
   npx supabase link --project-ref <project-ref>
   ```

   ```bash
   npx supabase db push
   ```

   o directamente con `psql`:

   ```bash
   psql "$SUPABASE_DB_URL" -f supabase/migrations/20261001120000_indice_guia.sql
   ```

3. Carga el índice. Si ya está en Chroma, copia esos mismos vectores sin cargar el modelo:

   ```bash
   ALMACEN=pgvector .venv/bin/python -m ingesta.indexar --desde-chroma
   ```

   o vectoriza el corpus desde cero:

   ```bash
   ALMACEN=pgvector .venv/bin/python -m ingesta.indexar
   ```

4. Compara la recuperación con Chroma (deja el resultado en `eval/resultados/`):

   ```bash
   .venv/bin/python eval/comparar_almacenes.py
   ```

La tabla guarda una sola configuración. Si cambia el corpus o la fragmentación, se vuelve a ejecutar
el paso 3; la consulta avisa si la tabla se cargó con otra configuración. Si cambia el modelo de
embeddings (y con él la dimensión), hace falta una migración nueva. Supabase pausa los proyectos
gratuitos tras una semana sin actividad: antes de una demo, revisa que el proyecto esté activo.

## Probar la recuperación

```bash
cd backend && ../.venv/bin/python -m app.rag.recuperar "¿Qué es un mapa de momentos críticos?" --etapa 7
```

`--sin-reranker` muestra el orden solo por similitud, para comparar. Con `ALMACEN=pgvector` (en el
entorno o en `.env`) consulta el índice de Supabase.

## Probar la generación

```bash
cd backend && ../.venv/bin/python -m app.rag.generar "¿Qué es un mapa de momentos críticos?" --etapa 7
```

`--json` muestra la respuesta con la forma del contrato de `/ia/consultar-guia` (`resultado`,
`encontrada`, `confianza`, `fuentes`…). `--filtrar-etapa` busca solo en la actividad de esa etapa.
En un Mac de 8 GB, con bge-m3, el reranker y gemma3:4b cargados a la vez, falta memoria y cada
respuesta tardó entre 50 s y 4 min. Una pregunta rechazada por el umbral no llama al LLM.

## Evaluar la recuperación

```bash
.venv/bin/python eval/comparar_embeddings.py
```

Compara modelos de embeddings con y sin reranker; necesita Ollama con `qwen3-embedding:0.6b` y
`embeddinggemma`. Para recalibrar el umbral de rechazo (sin LLM, ~9 min en un Mac de 8 GB):

```bash
.venv/bin/python eval/calibrar_umbral.py
```

Métricas y últimos resultados en [eval/README.md](eval/README.md).

## Chatbot de prueba

La interfaz de `src/` le pregunta a la API de `backend/app/api.py`, que llama a `generar.responder()`
y devuelve la respuesta con sus fuentes y su confianza. Se necesitan dos terminales, más Ollama
corriendo con `gemma3:4b`. Para consultar el índice de Supabase, pon `ALMACEN=pgvector` y
`SUPABASE_DB_URL` en `.env`.

```bash
cd backend && ../.venv/bin/uvicorn app.api:app --port 8000
```

```bash
npm install && npm run dev
```

Vite reenvía `/ia` a `http://localhost:8000` (cámbialo con `RAG_API_URL`), así que el backend no
necesita CORS. Las preguntas se atienden de a una y la primera carga los modelos, así que tarda más;
en un Mac de 8 GB cada respuesta puede tardar minutos. Si Ollama no está disponible, la API responde
503 con el motivo y la interfaz lo muestra en el chat. `GET /salud` muestra la configuración activa
y `http://localhost:8000/docs`, el esquema de la API.
