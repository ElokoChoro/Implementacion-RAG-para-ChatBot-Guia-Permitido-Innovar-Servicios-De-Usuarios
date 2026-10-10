"""
Revisión de entregables: contrasta el documento que sube la persona con lo que pide la guía
para su herramienta y devuelve un checklist con un resumen breve de lo cargado.

    POST /ia/adjuntos               el archivo leído, seudonimizado e indexado (app/adjuntos/)
    POST /ia/revisar-entregable     {"adjunto_id": "...", "herramienta": "perfil_persona_usuaria"}
      → revisar.revisar
          rubricas.cargar   lo que pide la guía, punto por punto (data/rubricas/<herramienta>.yaml)
          resumen           dos o tres frases sobre lo cargado, sin juicio de calidad (LLM)
          criterios         uno a la vez: chequeos.py sin LLM cuando se puede contar; si no, el
                            LLM con salida JSON (prompts.py). Nunca «cumple» sin evidencia que
                            esté en el documento.
      → tipos.Revision      resumen, cada criterio con estado, evidencia, sugerencia y página de
                            la guía, y `resultado`: el checklist en markdown para el chat

No juzga si el contenido es bueno o malo: solo revisa que esté lo que pide la guía
(acordado con UXLab). La revisión es una sugerencia para la persona, que la acepta,
la edita o la descarta.

Herramientas con rúbrica: perfil_persona_usuaria. Una herramienta nueva es un YAML
nuevo en data/rubricas/ y, si tiene criterios `revisa: codigo`, su chequeo en
chequeos.CHEQUEOS.

rubricas.py, tipos.py, chequeos.py y prompts.py no importan LlamaIndex ni modelos: los
usa también el simulador (MODO=simulador).
"""
