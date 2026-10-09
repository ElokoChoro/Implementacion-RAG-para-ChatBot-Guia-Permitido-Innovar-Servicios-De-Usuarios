"""
Adjuntos de la persona usuaria (PDF, DOCX y MD): leerlos, seudonimizarlos e indexarlos en memoria.

    POST /ia/adjuntos (multipart, campo «archivo»)
      → cargar.cargar_adjunto(nombre, datos)
          1. extraer.validar        formato (config.FORMATOS_ADJUNTO), contenido y tamaño, sin Docling
          2. extraer.extraer        texto con Docling, en secciones (página del PDF o título)
          3. seudonimizar           RUT, correos y teléfonos → [RUT_1], [CORREO_1], [TELEFONO_1],
                                    con los mismos marcadores en todo el documento
          4. indice.indexar         fragmentos y vectores en memoria, separados de la guía,
                                    hasta MINUTOS_ADJUNTO
      → tipos.AdjuntoCargado (id, páginas, fragmentos, datos reemplazados, vencimiento)
    DELETE /ia/adjuntos/{adjunto_id}  → indice.borrar

Por qué así: el adjunto trae datos de funcionarios y personas usuarias. Se
seudonimiza antes de convertirlo en vectores y no va a Chroma en disco ni a
Supabase. La tabla marcador → valor real queda solo en memoria, junto al
adjunto, para restaurar los valores en una respuesta a la misma persona. El
nombre del archivo y su texto no van al log.

Todavía no se responden preguntas sobre el adjunto ni se detectan nombres de
personas: solo RUT, correos y teléfonos, con reglas.

Funciones de cada módulo
------------------------
extraer.validar(nombre: str, datos: bytes) -> str
    El formato, o ErrorAdjunto (413, 415, 422). No importa Docling: la usa también el simulador.
extraer.extraer(nombre: str, datos: bytes) -> ArchivoExtraido
    Valida y convierte con Docling. ErrorAdjunto (413, 422) si no se puede leer o no tiene texto.
seudonimizar.seudonimizar(texto: str, correspondencias: dict[str, str] | None = None) -> Seudonimizado
    Con `correspondencias`, reutiliza sus marcadores y sigue su numeración.
seudonimizar.restaurar(texto: str, correspondencias: dict[str, str]) -> str
indice.indexar(archivo: ArchivoExtraido, correspondencias: dict[str, str],
               reemplazos: dict[str, int]) -> AdjuntoCargado
    Recibe el archivo ya seudonimizado.
indice.buscar(adjunto_id: str, consulta: str, top_k: int = config.TOP_K) -> list[NodeWithScore]
    Ordenados por el reranker. ErrorAdjunto(404) si no existe o venció.
indice.correspondencias(adjunto_id: str) -> dict[str, str]
indice.archivo(adjunto_id: str) -> ArchivoExtraido
    El adjunto seudonimizado completo, para la revisión de entregables (app/revision/).
indice.borrar(adjunto_id: str) -> bool
indice.vigentes() -> int
cargar.cargar_adjunto(nombre: str, datos: bytes) -> AdjuntoCargado

Metadatos de cada fragmento: origen="adjunto", adjunto_id, seccion (el título o
«Adjunto»), pagina_inicio y pagina_fin (0 si no hay página) y fuente («Adjunto,
p. 3», «Adjunto › <título>» o «Adjunto»). La fuente no lleva el nombre del
archivo, que puede traer nombres de personas.
"""
