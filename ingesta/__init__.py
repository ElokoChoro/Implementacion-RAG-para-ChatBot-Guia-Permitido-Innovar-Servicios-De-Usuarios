"""
Ingesta de la guía: extraer (Docling) -> corpus (páginas con metadatos) -> indexar (bge-m3).

Se ejecuta desde la raíz del repositorio:
    python -m ingesta.extraer /ruta/a/Guia_ComoInnovar.pdf
    python -m ingesta.corpus
    python -m ingesta.indexar
"""
import sys
from pathlib import Path

# El modelo de embeddings vive en backend/app/rag: la ingesta usa exactamente el
# mismo que la consulta (si cambia, hay que reindexar todo).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
