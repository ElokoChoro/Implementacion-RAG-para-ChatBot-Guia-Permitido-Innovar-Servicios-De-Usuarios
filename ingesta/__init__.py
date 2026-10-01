"""
Ingesta de la guía, en tres pasos que se ejecutan desde la raíz del repositorio:

    python -m ingesta.extraer /ruta/a/Guia_ComoInnovar.pdf   # PDF -> JSON de Docling
    python -m ingesta.corpus                                 # JSON -> data/corpus/v2/paginas.jsonl
    python -m ingesta.indexar                                # corpus -> índice vectorial

El corpus ya está versionado en el repositorio, así que para reconstruir el
índice basta con el último paso.
"""
import sys
from pathlib import Path

# La ingesta importa los modelos desde backend/app/rag para vectorizar la guía
# con exactamente el mismo modelo que después vectoriza las preguntas.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
