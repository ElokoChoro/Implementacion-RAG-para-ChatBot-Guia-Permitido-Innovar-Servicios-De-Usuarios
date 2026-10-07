"""
Tipos que comparten los pasos de los adjuntos y la API.

No importa LlamaIndex, Docling ni FlagEmbedding: lo usa también el simulador
(MODO=simulador), que corre solo con backend/requirements-simulador.txt.

`AdjuntoCargado` es la respuesta de POST /ia/adjuntos. Sigue las mismas reglas
que contrato.Respuesta: sus campos se comparan con `AdjuntoCargado` de
src/types.ts (CAMPOS_ADJUNTO en tests/conftest.py), y un campo nuevo solo se
agrega, con valor por defecto, y en los dos lados.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Los que sabe leer extraer.py. Los que acepta la API van en config.FORMATOS_ADJUNTO.
FORMATOS = ("pdf", "docx", "md")
# Respuesta cuando un adjunto no existe o ya venció (404).
NO_DISPONIBLE = "El documento ya no está disponible: vuelve a subirlo."


class ErrorAdjunto(Exception):
    """
    Problema con el archivo que la persona puede resolver.

    `mensaje` dice qué hacer («Quítale la contraseña al PDF y vuelve a subirlo.»).
    `estado` es el código HTTP con que responde la API: 413 tamaño o páginas,
    415 formato, 422 ilegible o sin texto, 404 adjunto inexistente o vencido.
    """

    def __init__(self, mensaje: str, estado: int = 422) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.estado = estado


@dataclass(frozen=True)
class Seccion:
    """Un trozo del adjunto: una página del PDF o el texto bajo un título del DOCX o MD."""

    texto: str
    pagina: int | None = None   # página del PDF, desde 1; None en DOCX y MD, que no tienen páginas
    titulo: str | None = None   # título bajo el que está el texto, si lo hay; sirve para citar


@dataclass
class ArchivoExtraido:
    """El texto de un adjunto, dividido en secciones."""

    nombre: str                 # nombre original: solo se le muestra a la persona, nunca va al log
    formato: str                # uno de FORMATOS
    secciones: list[Seccion]
    paginas: int | None = None  # total de páginas (PDF); None en DOCX y MD

    def texto(self) -> str:
        return "\n\n".join(s.texto for s in self.secciones)

    def caracteres(self) -> int:
        return len(self.texto())


@dataclass
class Seudonimizado:
    """Texto con los datos personales reemplazados por marcadores."""

    texto: str
    correspondencias: dict[str, str]  # marcador → valor real, p. ej. {"[RUT_1]": "12.345.678-5"}
    reemplazos: dict[str, int]        # tipo → apariciones reemplazadas, p. ej. {"RUT": 1, "CORREO": 2}


@dataclass
class AdjuntoCargado:
    """Respuesta de POST /ia/adjuntos: el adjunto quedó leído e indexado en memoria."""

    adjunto_id: str
    nombre: str
    formato: str
    paginas: int | None
    fragmentos: int
    caracteres: int
    reemplazos: dict[str, int] = field(default_factory=dict)
    expira_en_s: int = 0          # segundos que queda en memoria
    modo: str = "local"           # «local» (modelos) o «simulador» (respuesta fija)
    latencia_s: float = 0.0

    def a_dict(self) -> dict:
        return asdict(self)
