"""
Módulo RAG: responde preguntas usando solo la guía «¿Cómo podemos innovar en
los servicios públicos desde la experiencia usuaria?».

    config     configuración por variables de entorno
    modelos    embeddings (bge-m3), reranker (bge-reranker-v2-m3) y LLM (Ollama), locales
    indice     índice vectorial en Chroma
    recuperar  búsqueda de fragmentos para una pregunta
    prompts    prompt del asistente y frase de rechazo
    generar    respuesta con citas y confianza; umbral de rechazo
"""
