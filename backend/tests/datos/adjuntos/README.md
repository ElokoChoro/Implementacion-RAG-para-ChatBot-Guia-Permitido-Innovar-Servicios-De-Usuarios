# Adjuntos de ejemplo

Archivos para los tests de `backend/tests/test_adjuntos_*.py` y para probar la subida a mano. Todos
traen el mismo «Perfil de persona usuaria» con **datos ficticios**: un nombre, un RUT válido (dos
veces, en dos formatos), un correo y un teléfono.

| Archivo | Qué prueba |
| --- | --- |
| `perfil.md` | Markdown con títulos y una tabla |
| `perfil.docx` | El mismo contenido en Word |
| `perfil.pdf` | El mismo contenido en 3 páginas, con capa de texto |
| `escaneado.pdf` | Una página que es solo una imagen: sin texto que leer (no hay OCR) |
| `no-es-pdf.pdf` | Texto plano con extensión `.pdf` |

Se regeneran con `generar.py` (usa `cupsfilter` y `sips`, de macOS):

```bash
.venv/bin/python backend/tests/datos/adjuntos/generar.py
```
