# Módulo RAG · Permitido Innovar

Asistente que responde preguntas usando solo la guía «¿Cómo podemos innovar en los servicios públicos
desde la experiencia usuaria?», cita la sección y página de origen y funciona con modelos locales.

| Carpeta | Contenido |
| --- | --- |
| `src/` | Interfaz de chat de demo (React + Vite) |
| `backend/app/rag/` | Modelos, índice y recuperación del RAG |
| `ingesta/` | Extraer la guía → corpus con metadatos → índice vectorial |
| `data/corpus/` | Corpus extraído y versionado ([README](data/corpus/README.md)) |
| `data/fuentes/` | Manifiesto del PDF (el PDF no se versiona) |
| `eval/` | Set de preguntas y comparaciones de recuperación ([README](eval/README.md)) |

## Pipeline

```text
PDF ──Docling standard, sin OCR──▶ JSON ──▶ paginas.jsonl ──SentenceSplitter 400/50──▶ fragmentos
                                                                                      │ bge-m3 (FlagEmbedding)
pregunta ──bge-m3──▶ top 20 por coseno en Chroma ──bge-reranker-v2-m3──▶ top 4 ◀──────┘
```

| Pieza | Elección | Configuración (`backend/app/rag/config.py`) |
| --- | --- | --- |
| Extracción | Docling 2.131, pipeline `standard`, sin OCR | — |
| Corpus | `v1`, una página por bloque, págs. 13–161 | `VERSION_CORPUS` |
| Fragmentos | `SentenceSplitter` de LlamaIndex, 400 tokens, solapamiento 50 | `CHUNK_TOKENS`, `CHUNK_OVERLAP` |
| Embeddings | `BAAI/bge-m3` con FlagEmbedding, densos, 1024 dimensiones | `EMBEDDINGS` |
| Vector store | Chroma local, distancia coseno | `RUTA_CHROMA` |
| Reranker | `BAAI/bge-reranker-v2-m3` con FlagEmbedding, puntaje 0–1 | `RERANKER`, `RERANKER_CANDIDATOS`, `TOP_K`, `USAR_RERANKER` |
| Hardware | `mps`, `cuda:0` o `cpu`; fp16 por defecto | `DISPOSITIVO`, `FP16` |

## Decisiones de diseño

- **Docling `standard`, sin OCR.** Toma el texto de la capa de texto del PDF y un modelo de layout
  ordena las columnas y registra la página de cada bloque, que se usa para citar. El pipeline VLM de
  Docling, que lee cada página como imagen, se descartó: sobre esta guía inventa palabras (~6 % no
  existen en el PDF), tarda ~40 min y no guarda la página de cada bloque. El texto que está dentro de
  las láminas y fichas se incluye como párrafo `[Figura] …`.
- **Una página por registro en el corpus.** Cada página lleva sección, actividad, herramienta y etapa,
  para citar «sección, p. N» y filtrar por etapa.
- **bge-m3 + reranker.** bge-m3 es multilingüe, corre local y tiene licencia MIT. Comparado con
  qwen3-embedding:0.6b y embeddinggemma sobre el set de evaluación, los tres empatan (recall@4 de
  95,7 %). El reranker sube la recuperación a 97,9 % y ordena mejor los fragmentos (MRR de 0,906 a
  0,952), a cambio de ~5 s por pregunta. Detalle en [eval/README.md](eval/README.md).
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

## Reconstruir el índice

El corpus `v1` ya está en el repositorio, así que basta con indexar:

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

## Probar la recuperación

```bash
cd backend && ../.venv/bin/python -m app.rag.recuperar "¿Qué es un mapa de momentos críticos?" --etapa 7
```

`--sin-reranker` muestra el orden solo por similitud, para comparar.

## Evaluar la recuperación

```bash
.venv/bin/python eval/comparar_embeddings.py
```

Compara modelos de embeddings con y sin reranker; necesita Ollama con `qwen3-embedding:0.6b` y
`embeddinggemma`. Métricas y últimos resultados en [eval/README.md](eval/README.md).

## Interfaz de demo

```bash
npm install && npm run dev
```
