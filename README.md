<div align="center">

# 📘 Módulo RAG · Permitido Innovar

**Asistente que responde preguntas usando solo la guía**<br>
**«¿Cómo podemos innovar en los servicios públicos desde la experiencia usuaria?»**

Cita la sección y la página de cada respuesta, dice «No encuentro esa información en la guía.»
cuando la guía no responde y corre entero con modelos locales.

<br>

![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![LlamaIndex](https://img.shields.io/badge/LlamaIndex-0.14-7B3FE4?style=for-the-badge)
![Ollama](https://img.shields.io/badge/Ollama-gemma3:4b-000000?style=for-the-badge&logo=ollama&logoColor=white)
![Hugging Face](https://img.shields.io/badge/BAAI-bge--m3_+_reranker-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black)

![Chroma](https://img.shields.io/badge/Chroma-local-FF6446?style=for-the-badge)
![Supabase](https://img.shields.io/badge/Supabase-pgvector-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white)
![Docling](https://img.shields.io/badge/Docling-2.131-1F6FEB?style=for-the-badge)
![React](https://img.shields.io/badge/React-19_+_Vite-61DAFB?style=for-the-badge&logo=react&logoColor=black)

<br>

[Cómo funciona](#-cómo-funciona) ·
[Resultados](#-resultados) ·
[Inicio rápido](#-inicio-rápido) ·
[Supabase](#-índice-en-supabase-pgvector) ·
[Evaluación](eval/README.md) ·
[Para agentes de código](AGENTS.md)

</div>

---

## ✨ Qué hace

<table>
<tr>
<td width="50%" valign="top">

### 🎯 Responde solo desde la guía
Si ningún fragmento supera el umbral del reranker, contesta
«No encuentro esa información en la guía.» **sin llamar al LLM**: no hay contexto del que pueda
inventar.

</td>
<td width="50%" valign="top">

### 📍 Cita sección y página
Cada respuesta trae sus fuentes como «Sección › Herramienta, p. N», tomadas de los metadatos del
corpus, no del texto del LLM.

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🔒 Todo corre en local
Embeddings, reranker y LLM corren en tu equipo. Ni la guía ni las preguntas salen de él (salvo los
vectores, si eliges el índice en Supabase).

</td>
<td width="50%" valign="top">

### 📊 Medido, no supuesto
63 preguntas de evaluación, comparación de modelos, calibración del umbral y de la confianza. Los
resultados se versionan en [`eval/`](eval/README.md).

</td>
</tr>
</table>

---

## 📈 Resultados

Sobre el set de 63 preguntas y el corpus `v2` ([detalle](eval/README.md)), en un Mac M2 de 8 GB:

<div align="center">

| | Métrica | Valor |
| :---: | --- | :---: |
| 🔎 | Sección correcta entre los 4 fragmentos (`recall@4`, con reranker) | **98,0 %** |
| 🥇 | Posición del primer fragmento correcto (`MRR@4`) | **0,956** |
| 🚫 | Preguntas fuera de la guía rechazadas (umbral 0,5) | **100 %** |
| ✅ | Preguntas respondibles rechazadas por error | **0 %** |
| 🟢 | Respondibles con confianza `alta` (reranker ≥ 0,9) | **45 de 51** |

</div>

---

## 🧭 Cómo funciona

```mermaid
flowchart LR
    subgraph ING["📥 Ingesta (una vez)"]
        direction LR
        PDF["📄 PDF de la guía"] -->|"Docling standard<br>sin OCR"| JSON["JSON por página"]
        JSON --> CORPUS["paginas.jsonl<br>corpus v2"]
        CORPUS -->|"SentenceSplitter<br>400 / 50"| FRAG["221 fragmentos"]
        FRAG -->|"bge-m3"| IDX[("Índice<br>Chroma o pgvector")]
    end

    subgraph CON["💬 Consulta"]
        direction LR
        Q["❓ Pregunta"] -->|"bge-m3"| TOP20["Top 20<br>por coseno"]
        TOP20 -->|"bge-reranker-v2-m3"| TOP4["Top 4"]
        TOP4 --> U{"¿Algún fragmento<br>≥ 0,5?"}
        U -->|"no"| NO["🚫 «No encuentro esa<br>información en la guía.»"]
        U -->|"sí"| LLM["🦙 gemma3:4b<br>en Ollama"]
        LLM --> OK["✅ Respuesta + citas<br>+ confianza"]
    end

    IDX -.-> TOP20
```

| Pieza | Elección | Configuración ([`config.py`](backend/app/rag/config.py)) |
| --- | --- | --- |
| 📄 Extracción | Docling 2.131, pipeline `standard`, sin OCR | — |
| 📚 Corpus | `v2`, una página por registro: créditos (p. 2), prólogos (8–11) y págs. 13–163 | `VERSION_CORPUS` |
| ✂️ Fragmentos | `SentenceSplitter` de LlamaIndex, 400 tokens, solapamiento 50 | `CHUNK_TOKENS`, `CHUNK_OVERLAP` |
| 🧮 Embeddings | `BAAI/bge-m3` con FlagEmbedding, densos, 1024 dimensiones | `EMBEDDINGS` |
| 🗄️ Vector store | Chroma local o pgvector en Supabase, distancia coseno | `ALMACEN`, `RUTA_CHROMA`, `SUPABASE_DB_URL` |
| 🏅 Reranker | `BAAI/bge-reranker-v2-m3`, puntaje 0–1, 20 candidatos → 4 | `RERANKER`, `RERANKER_CANDIDATOS`, `TOP_K`, `USAR_RERANKER` |
| 🚧 Umbral | Puntaje del reranker ≥ 0,5; si nada llega, se rechaza sin LLM | `UMBRAL` |
| 🦙 LLM | `gemma3:4b` en Ollama, temperature 0,1, contexto de 4096 tokens | `LLM`, `TEMPERATURE`, `CONTEXTO_TOKENS`, `MAX_TOKENS_RESPUESTA` |
| 🎚️ Confianza | Mejor puntaje del reranker: `alta` ≥ 0,9, `media` ≥ 0,7, `baja` el resto | `CONFIANZA_ALTA`, `CONFIANZA_MEDIA` |
| 🖥️ Hardware | `mps`, `cuda:0` o `cpu`; fp16 por defecto | `DISPOSITIVO`, `FP16` |

Todos los parámetros se pueden cambiar por variable de entorno o en `.env`.

### La respuesta

`app.rag.generar --json` devuelve la forma del contrato de `POST /ia/consultar-guia`:

| Campo | Contenido |
| --- | --- |
| `resultado` | Texto de la respuesta, o «No encuentro esa información en la guía.» |
| `encontrada` | `false` si se rechazó por el umbral o por el LLM |
| `confianza` | `alta`, `media` o `baja`, según el reranker; `null` si no se encontró |
| `fuentes` | Lista con `seccion`, `pagina`, `fuente`, `fragmento` y `puntaje` de cada fragmento |
| `modelo`, `version_prompt`, `modo` | Qué generó la respuesta, para auditar |
| `puntaje`, `latencia_s` | Mejor puntaje del reranker y tiempo total |

---

## 🧠 Decisiones de diseño

<details>
<summary><b>Docling <code>standard</code>, sin OCR</b></summary>
<br>

Toma el texto de la capa de texto del PDF y un modelo de layout ordena las columnas y registra la
página de cada bloque, que se usa para citar. El pipeline VLM de Docling, que lee cada página como
imagen, se descartó: sobre esta guía inventa palabras (~6 % no existen en el PDF), tarda ~40 min y no
guarda la página de cada bloque. El texto que está dentro de las láminas y fichas se incluye como
párrafo `[Figura] …`.

</details>

<details>
<summary><b>Una página por registro en el corpus</b></summary>
<br>

Cada página lleva sección, actividad, herramienta y etapa, para citar «sección, p. N» y filtrar por
etapa. Formato en [data/corpus/README.md](data/corpus/README.md).

</details>

<details>
<summary><b>Créditos, prólogos y elaboración en el índice</b></summary>
<br>

El corpus `v1` empezaba en la Introducción, así que el asistente no podía decir quién hizo la guía,
cuándo ni con qué licencia. Desde `v2` también entran los créditos (p. 2), los prólogos (8–11) y
«¿Cómo elaboramos esta guía?» (162–163). Quedan fuera la portada, los índices, las referencias y la
contraportada. Los créditos se indexan como una ficha con los datos de la página: con el texto
extraído, el reranker no relacionaba «¿Quién es el autor de la guía?» con la autoría.

</details>

<details>
<summary><b>bge-m3 + reranker</b></summary>
<br>

bge-m3 es multilingüe, corre local y tiene licencia MIT. Comparado con qwen3-embedding:0.6b y
embeddinggemma sobre el set de evaluación, los tres empatan (recall@4 de 95,7 %). El reranker sube la
recuperación a 97,9 % y ordena mejor los fragmentos (MRR de 0,906 a 0,952), a cambio de ~5 s por
pregunta. Detalle en [eval/README.md](eval/README.md#comparación-de-modelos-de-embeddings).

</details>

<details>
<summary><b>Umbral antes del LLM y confianza desde el reranker</b></summary>
<br>

Si ningún fragmento supera el umbral, la guía no responde la pregunta y se contesta sin llamar al
LLM. El LLM todavía puede rechazar si los fragmentos no responden; el prompt lo obliga a empezar con
esa frase. La confianza y las fuentes salen del reranker y de los fragmentos, no del texto del LLM,
así que no dependen de que un modelo de 4B las escriba bien. Calibración en
[eval/README.md](eval/README.md#umbral-de-rechazo).

</details>

<details>
<summary><b>El corpus se versiona y el PDF no</b></summary>
<br>

El índice se reconstruye desde el corpus con un comando; el PDF se identifica por su SHA-256 en
[`data/fuentes/guia.yaml`](data/fuentes/guia.yaml).

</details>

---

## 🚀 Inicio rápido

> [!IMPORTANT]
> Necesitas **Python 3.12** y [Ollama](https://ollama.com/download). La primera ejecución descarga
> bge-m3 y el reranker desde Hugging Face (~2,3 GB cada uno); después corren sin red.

**1. Crea el entorno e instala las dependencias**

```bash
python3.12 -m venv .venv
```

```bash
.venv/bin/pip install -r ingesta/requirements.txt
```

La consulta sola (sin Docling) necesita únicamente `backend/requirements.txt`.

**2. Descarga el LLM (~3,3 GB)**

```bash
ollama pull gemma3:4b
```

**3. Construye el índice.** El corpus `v2` ya está en el repositorio, así que basta con indexar:

```bash
.venv/bin/python -m ingesta.indexar
```

**4. Pregunta** (desde `backend/`):

```bash
cd backend && ../.venv/bin/python -m app.rag.generar "¿Qué es un mapa de momentos críticos?" --etapa 7
```

| Opción | Qué hace |
| --- | --- |
| `--json` | Muestra la respuesta con la forma del contrato |
| `--etapa N` | Le da al LLM el contexto de la etapa del proyecto (1 a 7) desde la que se pregunta: actividad, objetivo y herramientas ([`guia.py`](backend/app/rag/guia.py)). Se ve con `python -m app.rag.prompts --etapa N` |
| `--filtrar-etapa` | Busca solo en la actividad de esa etapa |

Para ver solo la recuperación, sin LLM:

```bash
cd backend && ../.venv/bin/python -m app.rag.recuperar "¿Qué es un mapa de momentos críticos?" --etapa 7
```

Aquí `--etapa` filtra por etapa y `--sin-reranker` muestra el orden solo por similitud, para comparar.

> [!NOTE]
> En un Mac de 8 GB, con bge-m3, el reranker y gemma3:4b cargados a la vez, falta memoria y cada
> respuesta tarda entre 50 s y 4 min. Una pregunta rechazada por el umbral no llama al LLM.

<details>
<summary><b>🔁 Regenerar el corpus desde el PDF</b></summary>
<br>

Por ejemplo, si cambia la guía o la versión de Docling:

```bash
.venv/bin/python -m ingesta.extraer "/ruta/a/Guia_ComoInnovar.pdf"
```

```bash
.venv/bin/python -m ingesta.corpus
```

`ingesta.extraer` compara el hash del PDF con `data/fuentes/guia.yaml`. `ingesta.corpus --ver 148`
muestra cómo quedó una página. Un cambio que altere el corpus va en una versión nueva
(`data/corpus/v3/`), no sobre `v2`.

</details>

---

## 🐘 Índice en Supabase (pgvector)

Con `ALMACEN=pgvector` el índice vive en Supabase, en la tabla `public.data_guia_fragmentos`
(`vector(1024)`, índice HNSW por coseno y RLS sin políticas, así que la API pública no la lee). Los
embeddings se siguen calculando en local; a Supabase solo llegan los vectores, el texto y los
metadatos.

<details>
<summary><b>Configurar paso a paso</b></summary>
<br>

1. Copia `.env.example` como `.env` y completa `SUPABASE_DB_URL` con el connection string del
   *Session pooler* (Project Settings › Database › Connection string) y la contraseña de la base.
2. Aplica la migración con la [CLI de Supabase](https://supabase.com/docs/guides/cli):

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
embeddings (y con él la dimensión), hace falta una migración nueva.

</details>

Chroma y pgvector devuelven los mismos 20 candidatos, en el mismo orden, en las 52 preguntas;
pgvector suma ~0,8 s por pregunta por la ida y vuelta a Supabase.

> [!WARNING]
> `SUPABASE_DB_URL` da acceso completo a la base: va solo en `.env` y nunca en el frontend. Supabase
> pausa los proyectos gratuitos tras una semana sin actividad: antes de una demo, revisa que el
> proyecto esté activo.

---

## 🧪 Evaluación

| Script | Qué hace | Requisitos |
| --- | --- | --- |
| [`calibrar_umbral.py`](eval/calibrar_umbral.py) | Prueba umbrales de rechazo y cortes de confianza (sin LLM, ~9 min) | — |
| [`comparar_embeddings.py`](eval/comparar_embeddings.py) | Compara bge-m3, qwen3-embedding y embeddinggemma, con y sin reranker | Ollama con `qwen3-embedding:0.6b` y `embeddinggemma` |
| [`comparar_almacenes.py`](eval/comparar_almacenes.py) | Compara la recuperación en Chroma y en pgvector | Los dos índices y `SUPABASE_DB_URL` |

```bash
.venv/bin/python eval/calibrar_umbral.py
```

Métricas, tablas y últimos resultados en [eval/README.md](eval/README.md).

---

## 💻 Chatbot de prueba

La interfaz de chat (React 19 + Vite + TypeScript) le pregunta a la API de
[`backend/app/api.py`](backend/app/api.py), que llama a `generar.responder()` y devuelve la respuesta
con sus fuentes y su confianza. Se necesitan dos terminales, más Ollama corriendo con `gemma3:4b`.
Para consultar el índice de Supabase, pon `ALMACEN=pgvector` y `SUPABASE_DB_URL` en `.env`.

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

---

## ✅ Tests y CI

Los tests de [`backend/tests/`](backend/tests/) prueban lo que decide el backend sin cargar modelos
ni llamar a Ollama: el umbral, la confianza, las fuentes, la detección del rechazo del LLM, los
campos del contrato y la validación de la API. Corren en segundos.

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/ruff check
```

No miden la calidad de las respuestas: eso lo hacen los scripts de [`eval/`](eval/). El
[CI](.github/workflows/ci.yml) corre `ruff check` y `pytest` para el backend, y `npm run lint` y
`npm run build` para el chatbot, en cada PR y en cada push a `main`. Dependabot propone una vez al
mes las actualizaciones de npm, pip y GitHub Actions.

---

## 🗂️ Estructura

```text
.
├── backend/
│   ├── app/api.py          API HTTP (FastAPI): POST /ia/consultar-guia
│   ├── app/rag/            Consulta: config, modelos, indice, recuperar, guia, prompts, generar
│   └── tests/              Tests con pytest, sin modelos ni Ollama
├── ingesta/                PDF → JSON de Docling → corpus → índice vectorial
├── data/
│   ├── corpus/v2/          Corpus versionado, una página por línea (paginas.jsonl)
│   └── fuentes/guia.yaml   Manifiesto y SHA-256 del PDF (el PDF no se versiona)
├── eval/                   Preguntas, scripts de comparación y calibración, resultados
├── supabase/migrations/    Tabla public.data_guia_fragmentos con pgvector
├── src/                    Chatbot de prueba (React + Vite), conectado a la API
└── .github/                CI (lint, tipos, build y tests) y Dependabot
```

---

## 📜 Licencia y créditos

La guía **«¿Cómo podemos innovar en los servicios públicos desde la experiencia usuaria?»**, de la
serie *Permitido Innovar: Guías para transformar el Estado chileno*, es del Laboratorio de Gobierno
(Ministerio de Hacienda, Gobierno de Chile) y del Observatorio UX de la Universidad Tecnológica
Metropolitana (2025). Se publica con licencia
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.es), que también aplica al
corpus derivado en `data/corpus/`.

<div align="center">
<br>
<sub>Hecho en Chile 🇨🇱 · Modelos locales · Tus preguntas no salen del equipo</sub>
</div>
