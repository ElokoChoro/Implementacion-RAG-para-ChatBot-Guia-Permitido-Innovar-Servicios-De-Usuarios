# Evaluación

## Set de preguntas

`preguntas_v1.jsonl` tiene 58 preguntas sobre la guía, una por línea:

| Campo | Contenido |
| --- | --- |
| `id` | `P-001` … `P-058` |
| `pregunta` | Como la haría una persona usuaria |
| `respuesta_esperada` | Resumen de lo que dice la guía |
| `seccion_fuente`, `pagina` | Dónde está la respuesta; vacíos si la guía no la responde |
| `etapa` | 1 a 7 si la pregunta es de una etapa de la plataforma |
| `categoria` | `respondible`, `fuera` (la guía no lo responde) o `ambigua` |
| `dificultad` | `baja`, `media` o `alta` |

47 preguntas tienen sección esperada; son las que se usan para medir la recuperación.

## Métricas de recuperación

Se miran los primeros `k` fragmentos recuperados para cada pregunta:

| Métrica | Qué mide |
| --- | --- |
| `recall@k` | % de preguntas en que algún fragmento es de la sección esperada (actividad, herramienta o sección de la guía) |
| `recall_pagina@k` | % de preguntas en que algún fragmento es de la página esperada |
| `mrr@k` | Promedio de 1/posición del primer fragmento de la sección esperada (0 si no está). Premia que llegue arriba |

## Comparación de modelos de embeddings

`comparar_embeddings.py` compara bge-m3 con qwen3-embedding:0.6b y embeddinggemma, con y sin el
reranker (20 candidatos → 4). Uso y requisitos en el propio script. Resultado del 2026-09-30, en un
Mac M2 de 8 GB (`resultados/comparacion_embeddings.json`):

| Modelo | `recall@4` | `recall@20` | Con reranker: `recall@4` | `recall_pagina@4` | `mrr@4` |
| --- | --- | --- | --- | --- | --- |
| **bge-m3** | 95,7 | 100 | **97,9** | 91,5 | 0,952 |
| qwen3-embedding:0.6b | 95,7 | 100 | 100 | 91,5 | 0,957 |
| embeddinggemma | 95,7 | 100 | 97,9 | 91,5 | 0,952 |

- Los tres empatan: todos dejan la sección correcta entre los 20 candidatos. La diferencia con
  reranker es una sola pregunta.
- Esa pregunta, P-009 («¿Qué preguntas propone la guía para trabajar las necesidades…?»), espera
  *Necesidades, p. 132*, pero la *Introducción, p. 19* es una lista de preguntas sobre «las
  necesidades y expectativas de las personas usuarias». El reranker la prefiere con 20, 30 o 40
  candidatos; qwen3 acierta solo porque la p. 19 no quedó entre sus candidatos. Filtrando por la
  etapa 4 se resuelve con cualquier modelo.
- El reranker mejora a los tres modelos: recall@4 de 95,7 a 97,9–100 y MRR de ~0,90 a ~0,95. Suma
  unos 5 s por pregunta con 20 candidatos.

## Umbral de rechazo

`calibrar_umbral.py` recupera los 4 fragmentos de cada una de las 58 preguntas con el reranker (sin
LLM) y prueba umbrales sobre el mejor puntaje. Si ningún fragmento llega al umbral, se responde «No
encuentro esa información en la guía.» sin llamar al LLM. Resultado del 2026-09-30
(`resultados/umbral.json`):

| Umbral | Rechazo de las 9 `fuera` | Falsos «no encuentro» (46 `respondible`) | `recall@4` tras el corte | Ambiguas rechazadas (de 3) |
| --- | --- | --- | --- | --- |
| 0,1 | 77,8 | 0 | 97,8 | 0 |
| 0,3 | 88,9 | 0 | 97,8 | 2 |
| **0,5** | **100** | **0** | **97,8** | 3 |
| 0,8 | 100 | 0 | 97,8 | 3 |
| 0,9 | 100 | 6,5 | 89,1 | 3 |

- El reranker separa muy bien las dos clases: las preguntas de fuera llegan como máximo a 0,398 (P-055,
  presupuesto mínimo, cerca del Plan de comunicaciones) y las respondibles parten en 0,831 (P-018).
  Cualquier umbral entre 0,4 y 0,8 acierta en todas.
- Se eligió 0,5: más cerca del lado de las de fuera, porque es peor callar una pregunta que la guía
  responde que dejar pasar una de fuera al LLM, que igual puede rechazarla. Con 0,5 el LLM recibe en
  promedio 3,1 fragmentos (2,9 con 0,6).
- Las 3 preguntas ambiguas quedan bajo el umbral (0,16 a 0,44). En vez de pedir aclaración, se
  rechazan con una sugerencia: reformular con el nombre de la herramienta o indicar la etapa.
- **Confianza**: 43 de las 46 respondibles tienen un mejor puntaje de 0,9 o más (93 % con la sección
  esperada en primer lugar) y 3 están entre 0,7 y 0,9. Por eso `alta` va desde 0,9, `media` desde 0,7
  y `baja` entre el umbral y 0,7.
- El set tiene solo 9 preguntas de fuera. Conviene recalibrar al ampliarlo y siempre que cambie el
  reranker, porque los puntajes no son comparables entre modelos.


## Chroma y pgvector

`comparar_almacenes.py` recupera los 20 candidatos de cada pregunta (sin reranker) en Chroma y en
pgvector (Supabase) y compara los fragmentos, los puntajes y el recall de cada uno. Con el índice
copiado desde Chroma (`ingesta.indexar --desde-chroma`) los dos tienen los mismos vectores y
deberían coincidir. Resultado del 2026-10-01, con los 207 fragmentos de `guia_v1_bge-m3_c400o50`
copiados a Supabase (`resultados/comparacion_almacenes.json`):

| Almacén | `recall@4` | `mrr@4` | `recall@20` | Segundos por pregunta |
| --- | --- | --- | --- | --- |
| Chroma (local) | 95,7 | 0,906 | 100 | 0,26 |
| pgvector (Supabase, `sa-east-1`) | 95,7 | 0,906 | 100 | 1,03 |

- Los dos devuelven los mismos 20 candidatos, en el mismo orden, en las 47 preguntas.
- El puntaje de similitud cambia de escala, no de orden: Chroma entrega `exp(-distancia)` y
  pgvector `1 - distancia` (las distancias coinciden hasta 10⁻⁶). No afecta al umbral ni a la
  confianza, que usan el puntaje del reranker; sí habría que recalibrar si se usara el umbral sin
  reranker.
- pgvector suma ~0,8 s por pregunta por la ida y vuelta a Supabase, poco frente a los ~5 s del
  reranker.
