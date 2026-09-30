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
| `categoria` | `respondible`, `fuera_de_guia` o `ambigua` |
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
