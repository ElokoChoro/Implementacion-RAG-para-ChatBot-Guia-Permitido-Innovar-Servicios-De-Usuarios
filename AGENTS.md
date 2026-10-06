# AGENTS.md

Instrucciones para agentes de código (Claude Code, Codex, Cursor, etc.) que trabajan en este
repositorio. El detalle del pipeline, la instalación y los resultados está en [README.md](README.md)
y [eval/README.md](eval/README.md); aquí va lo que hace falta para cambiar el código sin romperlo.

## Qué es

Módulo RAG que responde preguntas usando **solo** la guía «¿Cómo podemos innovar en los servicios
públicos desde la experiencia usuaria?» (Permitido Innovar), cita sección y página, y corre con
modelos locales. Si la guía no responde, contesta «No encuentro esa información en la guía.».

| Carpeta | Contenido |
| --- | --- |
| `backend/app/rag/` | Consulta: `config`, `modelos`, `indice`, `recuperar`, `guia`, `prompts`, `generar`. Asistente por etapa: `prompts_etapa`, `sugerir`. Umbral, llamada al LLM y armado de la respuesta, comunes a los dos: `flujo`. Forma de la respuesta: `contrato`; respuestas fijas sin modelos: `simulador`; log por consulta: `registro` |
| `backend/app/api.py` | API HTTP (FastAPI): `POST /ia/consultar-guia`, `POST /ia/sugerir-proximos-pasos` y `GET /salud`; atiende las solicitudes de a una, con tope de cola (`COLA_MAXIMA`, `ESPERA_TURNO_S`) y 503 si no hay turno. Con `MODO=simulador` responde `simulador.py` y corre solo con `backend/requirements-simulador.txt`; con `CLAVE_SERVICIO`, exige `Authorization: Bearer` |
| `backend/tests/` | Tests con pytest: umbral, confianza, fuentes, contrato y validación de la API, etapas y su contexto, sin modelos ni Ollama |
| `ingesta/` | PDF → JSON de Docling (`extraer`) → corpus (`corpus`) → índice vectorial (`indexar`) |
| `data/corpus/v2/` | Corpus vigente, una página por línea (`paginas.jsonl`) |
| `data/fuentes/guia.yaml` | Manifiesto y SHA-256 del PDF (el PDF no se versiona) |
| `eval/` | Set de preguntas, scripts de comparación y calibración, resultados en `eval/resultados/` |
| `supabase/migrations/` | Tabla `public.data_guia_fragmentos` con pgvector |
| `src/` | Chatbot de prueba (React 19 + Vite + TypeScript). Llama a la API mediante el proxy de Vite (`/ia` → puerto 8000) |
| `.github/` | CI (`ruff`, `pytest`, `oxlint`, `tsc` y `vite build` en cada PR) y Dependabot |

Pipeline: Docling `standard` sin OCR → `SentenceSplitter` 400/50 → `BAAI/bge-m3` → Chroma o
pgvector (coseno, 20 candidatos) → `BAAI/bge-reranker-v2-m3` (top 4) → umbral 0,5 →
`gemma3:4b` en Ollama (o, con `PROVEEDOR_LLM=openai`, un servidor compatible con OpenAI como LM Studio).

## Comandos

Python 3.12 con el entorno en `.venv/`. **Ojo con el directorio**: la consulta se ejecuta desde
`backend/`; la ingesta y la evaluación, desde la raíz.

```bash
python3.12 -m venv .venv          # ingesta, consulta, pytest y ruff, con las versiones del lock:
.venv/bin/pip install -r ingesta/requirements.txt -r requirements-dev.txt -c requirements.lock
.venv/bin/python -m pytest                                 # tests, en segundos (config en pyproject.toml)
.venv/bin/ruff check                                       # lint de Python
.venv/bin/python -m ingesta.indexar                        # reconstruye el índice (Chroma)
ALMACEN=pgvector .venv/bin/python -m ingesta.indexar --desde-chroma   # copia el índice a Supabase
.venv/bin/python -m ingesta.corpus --ver 148               # muestra cómo quedó una página
cd backend && ../.venv/bin/python -m app.rag.recuperar "¿Qué es un mapa de momentos críticos?" --etapa 7
cd backend && ../.venv/bin/python -m app.rag.generar "¿Qué es un plano del servicio?" --json
cd backend && ../.venv/bin/python -m app.rag.prompts --etapa 7   # contexto de la etapa que recibe el LLM
cd backend && ../.venv/bin/python -m app.rag.sugerir 4 --ver-prompt   # asistente por etapa, sin LLM
cd backend && ../.venv/bin/uvicorn app.api:app --port 8000   # API para el chatbot (npm run dev en otra terminal)
cd backend && MODO=simulador ../.venv/bin/uvicorn app.api:app --port 8000   # API con respuestas fijas, sin modelos
.venv/bin/python eval/calibrar_umbral.py                   # umbral y cortes de confianza
.venv/bin/python eval/probar_asistente_etapa.py            # prompt del asistente por etapa (con LLM)
.venv/bin/python eval/comparar_embeddings.py               # necesita Ollama con qwen3-embedding y embeddinggemma
.venv/bin/python eval/comparar_almacenes.py                # necesita los dos índices y SUPABASE_DB_URL
```

Frontend:

```bash
npm install && npm run dev
npm run build    # tsc -b + vite build
npm run lint     # oxlint
```

Antes de abrir un PR: `ruff check`, `pytest`, `npm run lint` y `npm run build` sin errores; el CI
corre lo mismo. Los tests reemplazan la recuperación y el LLM, así que no miden la calidad de las
respuestas: si el cambio toca recuperación, umbral o prompt, prueba también con `app.rag.recuperar`
o `app.rag.generar` y corre el script de `eval/` que corresponda. Una regla nueva del backend que
no dependa de los modelos (un corte, un campo, una validación) lleva su test en `backend/tests/`.

Requisitos de los modelos: la primera ejecución descarga bge-m3 y el reranker desde Hugging Face
(~2,3 GB cada uno). La generación necesita Ollama corriendo con `ollama pull gemma3:4b` o, con
`PROVEEDOR_LLM=openai`, otro servidor compatible con la API de OpenAI, en el mismo equipo o en otro
(README, «LLM en cada equipo»). Todo cliente del LLM se crea en `llm()`, sus errores se traducen
en `flujo.chat()` y sus tokens se leen en `flujo.tokens()`: un proveedor nuevo va en esos lugares. El equipo
de referencia es un Mac M2 de 8 GB: no cargues más modelos de los necesarios en un mismo proceso y
usa siempre `embedding()`, `reordenador()` y `llm()` de `modelos.py`, que crean una sola instancia.

## Invariantes (qué obliga a qué)

- **Configuración**: todo parámetro va en `backend/app/rag/config.py`, leído con `_env()` para que
  se pueda cambiar por variable de entorno. Una variable nueva se documenta en el docstring del
  módulo. Si es una credencial, se lee del entorno o `.env` y, si no está, del llavero (ver
  `secretos.py`), y `.env.example` explica cómo guardarla.
- **Cambiar `EMBEDDINGS`, `CHUNK_TOKENS`, `CHUNK_OVERLAP` o `VERSION_CORPUS`** → volver a indexar.
  En Chroma cada combinación tiene su colección (`config.coleccion()`); en pgvector hay una sola
  tabla que se recarga completa. `indice()` abre el índice una vez por proceso: si indexas con la
  API corriendo, reiníciala.
- **Cambiar el modelo de embeddings** (y con él `EMBEDDINGS_DIM`) → migración nueva en
  `supabase/migrations/` con la dimensión del modelo.
- **Cambiar `RERANKER`** → recalibrar `UMBRAL`, `CONFIANZA_MEDIA` y `CONFIANZA_ALTA` con
  `eval/calibrar_umbral.py`: los puntajes no son comparables entre modelos.
- **Prompt** (`prompts.py`, y los datos de `guia.py` que llegan al LLM: nombre, actividad y objetivo
  de cada etapa, nombre del propósito y nombres de `HERRAMIENTAS`): todo cambio sube `VERSION_PROMPT` y se anota en la lista de versiones
  del docstring. Lo mismo con el prompt del asistente por etapa (`prompts_etapa.py`,
  `VERSION_PROMPT_ETAPA`), que también recibe esos datos de `guia.py` y se prueba con
  `eval/probar_asistente_etapa.py`. `test_huella_prompt.py` falla si cambian los mensajes al LLM sin
  subir la versión: al subirla, agrega la huella nueva. `flujo.armar_respuesta()` detecta el rechazo
  del LLM buscando `MENSAJE_NO_ENCONTRADA` al **inicio** de la respuesta: si cambias esa frase o la
  regla del caso C, revisa `prompts.py` y `flujo.py`.
- **Confianza y fuentes** salen del puntaje del reranker y de los metadatos de los fragmentos, nunca
  del texto del LLM. `Respuesta` en `contrato.py` tiene la forma del contrato `POST /ia/consultar-guia`:
  no cambies sus campos sin acordarlo. Los tests comparan sus campos con `CAMPOS_CONTRATO` y los
  de cada fuente (`Fuente`) con `CAMPOS_FUENTE` (`backend/tests/conftest.py`), copias de
  `RespuestaGuia` de `src/lib/rag.ts` y `Fuente` de `src/types.ts`; si el cambio se acuerda,
  actualiza los tres lugares, y también las respuestas de `simulador.py`.
- **Simulador**: `contrato.py`, `simulador.py`, `config.py`, `secretos.py`, `registro.py`, `prompts.py`, `prompts_etapa.py` y `guia.py`
  no importan LlamaIndex, FlagEmbedding ni clientes de LLM (o lo hacen dentro de una función), para
  que `MODO=simulador` corra con `backend/requirements-simulador.txt`. `test_simulador.py` lo revisa.
- **Corpus**: `data/corpus/v2/paginas.jsonl` no se edita a mano; se regenera con `ingesta.corpus`.
  Un cambio de extracción o de metadatos que altere el corpus va en una versión nueva
  (`data/corpus/v3/`), no sobre `v2`. Las tablas de la guía (`SECCIONES`, `ACTIVIDADES`,
  `HERRAMIENTAS`) y la etapa → actividad del Propósito 1 están en `backend/app/rag/guia.py`, que
  comparten la ingesta y el prompt: cambiarlas cambia el corpus. Los créditos (p. 2) se indexan como `FICHA_CREDITOS`
  (`ingesta/corpus.py`); si cambia la guía, revísala contra la página. Formato en [data/corpus/README.md](data/corpus/README.md).
- **Dependencias de Python**: un cambio en los `requirements*.txt` va con `requirements.lock`
  regenerado (comando en el README, «Tests y CI»). El lock fija las versiones con que se midió
  `eval/`; si sube llama-index, FlagEmbedding, transformers, torch o Docling, corre la evaluación
  que corresponda.
- **Evaluación**: los resultados de `eval/resultados/*.json` se versionan. Si vuelves a correr un
  script, actualiza la tabla correspondiente de `eval/README.md` con la fecha.
- **Migraciones**: nunca edites una migración ya aplicada; agrega una nueva con fecha en el nombre.
  La tabla del índice tiene RLS activo y sin políticas a propósito: solo el backend la lee, con la
  conexión directa a Postgres.

## Seguridad y datos

- `SUPABASE_DB_URL` da acceso completo a la base: se guarda con
  `python -m app.rag.secretos guardar SUPABASE_DB_URL` (desde `backend/`), que usa el llavero del
  sistema si el equipo tiene uno y si no la escribe en `.env` con permisos 600 (WSL, Linux sin
  escritorio). Nunca va en el frontend. El código la lee con `config.supabase_db_url()`: primero el
  entorno o `.env`, después el llavero. Una credencial nueva se agrega a `SECRETOS` en `secretos.py`.
  Vite expone al navegador las variables con prefijo `VITE_`: ninguna credencial lo lleva.
- No se versionan el PDF de la guía, `data/docling/` (salida cruda de Docling) ni `storage/`
  (índice de Chroma). Se regeneran con los scripts de `ingesta/`.
- Todo corre en local: no agregues llamadas a APIs externas con el texto de la guía o las
  preguntas sin acordarlo.
- La guía tiene licencia CC BY-NC-SA 4.0.

## Estilo

- **Idioma**: español de Chile, trato de «tú», frases cortas. Nombres de módulos, funciones y
  variables en español (`recuperar`, `responder`, `fragmentos`), salvo los términos técnicos
  habituales (`embedding`, `reranker`, `chunk`). Decimales con coma en prosa («0,5»), comillas
  «angulares».
- **Python**: `from __future__ import annotations`, type hints, docstrings de módulo que explican
  qué hace el paso, por qué se eligió así y cómo probarlo desde la terminal. Cada script tiene una
  CLI con `argparse` y `description=__doc__`. Los errores para la persona usuaria dicen qué hacer
  («Inicia Ollama (ollama serve).»). Líneas de hasta 120 caracteres; ruff ordena los imports
  (`ruff check --fix`).
- **Comentarios**: explican el motivo de cada valor o decisión con el dato que lo respalda (ver
  `config.py`). El motivo se escribe en el propio repo (docstring, README, `eval/README.md`): no
  cites documentos externos ni IDs de gestión (`ADR-NN`, `T-NNN`, `EXP-NN`, `R-NN`, `RF-NN`).
- **TypeScript**: modo `strict`, componentes funcionales, sin punto y coma, comillas simples, tipos
  en `src/types.ts`.

## Git

- Ramas desde `main` (`feature/<tema>`); se integran por PR.
- Mensajes en español con prefijo (`feat:`, `fix:`, `eval:`, `docs:`, `refactor:`): una línea de
  resumen y, si hace falta, viñetas con qué cambió y por qué, con las cifras de la evaluación cuando
  las haya.
- Commits y PR **sin líneas de atribución** a herramientas de IA (`Co-Authored-By`, «Generated
  with…»).
