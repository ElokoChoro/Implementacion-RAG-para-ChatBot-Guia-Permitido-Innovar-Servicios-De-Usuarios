# Corpus de la guía

Texto extraído de **«¿Cómo podemos innovar en los servicios públicos desde la experiencia usuaria?»**,
de la serie *Permitido Innovar: Guías para transformar el Estado chileno* (2025).
Autoría: Laboratorio de Gobierno (Ministerio de Hacienda), Gobierno de Chile, y Observatorio UX de la
Universidad Tecnológica Metropolitana.

Licencia: [Creative Commons BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.es).
Este corpus es una obra derivada y se comparte con la misma licencia, sin fines comerciales.

## Versiones

| Versión | Extracción | Archivo |
| --- | --- | --- |
| `v1` | Docling 2.131 `standard`, sin OCR; págs. 13 a 161. Ya no se versiona: `v2` lo contiene completo (está en el historial de git, en el commit `21eed4b`) | — |
| `v2` | Igual que `v1`, más créditos (pág. 2), prólogos (8 a 11) y «¿Cómo elaboramos esta guía?» (162 y 163). Las páginas de `v1` no cambian | `v2/paginas.jsonl` |
| `v3` | Las mismas páginas y metadatos que `v2`, con el texto limpio (`ingesta/limpieza.py`): palabras cortadas con guion unidas, títulos de herramienta ordenados, párrafos partidos unidos, pasos numerados, sin números ni letras sueltas, sin las figuras de muestra de las págs. 52-53 ni las que repiten una tabla. Cambian 68 páginas | `v3/paginas.jsonl` |

Cada línea de `paginas.jsonl` es una página (en `v2` y `v3`: págs. 2, 8 a 11 y 13 a 163, sin portadillas casi vacías):

| Campo | Ejemplo |
| --- | --- |
| `id` | `guia-p148` |
| `texto` | Markdown de la página; el texto de las figuras va como párrafo `[Figura] …` |
| `fuente` | `Personas › Perfil de persona usuaria, p. 148` |
| `pagina_inicio`, `pagina_fin` | `148` |
| `seccion`, `actividad`, `herramienta` | según el índice de la guía |
| `etapa` | 1 a 7 (etapas del Propósito 1 en SSP-UXLab) o `null` |
| `version_corpus` | `v3` |

El PDF original no se versiona: su manifiesto (hash, páginas y versión del extractor) está en
`data/fuentes/guia.yaml`. Para regenerar el corpus, ver el README de la raíz.

El texto no se corrige a mano, ni aquí ni en la base de datos: un vector calculado con el texto
original no cambia si se edita el texto, y la próxima indexación borraría el cambio. Las
correcciones van en `ingesta/limpieza.py` (una regla o una entrada de `CORRECCIONES`) y se
regenera el corpus en una versión nueva. Para comparar una página antes y después de la limpieza:
`python -m ingesta.corpus --ver 128 --crudo`.
