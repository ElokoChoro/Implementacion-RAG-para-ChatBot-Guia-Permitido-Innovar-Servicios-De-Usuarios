"""
Módulo RAG: responde preguntas usando solo la guía «¿Cómo podemos innovar en
los servicios públicos desde la experiencia usuaria?».

    config     configuración por variables de entorno
    modelos    embeddings (bge-m3) y reranker (bge-reranker-v2-m3) locales; cliente del LLM
    indice     índice vectorial en Chroma (local) o pgvector (Supabase)
    recuperar  búsqueda de fragmentos para una pregunta
    guia       estructura de la guía y etapas de la plataforma, como datos
    prompts    prompt del asistente y frase de rechazo
    generar    respuesta con citas y confianza; umbral de rechazo
"""
