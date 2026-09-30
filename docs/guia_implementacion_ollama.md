# Guía de Implementación Local con Ollama

Esta guía explica paso a paso cómo cualquier miembro del equipo puede configurar y ejecutar el modelo de IA localmente en su propio PC utilizando **Ollama**, integrando automáticamente el *System Prompt* de limitaciones que hemos definido.

## Requisitos Previos

1. **Tener Ollama instalado:** Si aún no lo tienes, descárgalo e instálalo.
2. **Terminal:** Puedes usar PowerShell, CMD o Git Bash en tu PC.
3. **Repositorio actualizado:** Asegúrate de hacer un `git pull` para tener la última versión del código en tu máquina, incluyendo el archivo `Modelfile` que está en la raíz del proyecto.

## Paso a Paso

### 1. Abrir la terminal en el proyecto
Abre tu terminal (PowerShell) y navega hasta la carpeta raíz del proyecto (donde se encuentra el archivo llamado `Modelfile`).

Este `Modelfile` ya contiene el modelo base que usaremos y el *System Prompt* con todas las reglas, tono formal y limitaciones del asistente.

### 2. Crear el Modelo Personalizado
Para compilar y crear el modelo en tu entorno local, ejecuta el siguiente comando:

```powershell
ollama create asistente-innovar -f Modelfile
```

> **Nota:** Al ejecutar este comando, Ollama leerá el archivo. Si es la primera vez y no tienes el modelo base descargado (por ejemplo, `gemma:2b` o `llama3`), Ollama comenzará a descargarlo automáticamente. Esto puede tomar un par de minutos dependiendo de la velocidad de tu internet.

### 3. Ejecutar y Probar el Modelo
Una vez que el terminal te confirme que el modelo fue creado exitosamente (`success`), puedes levantar el chatbot y empezar a chatear con él desde la misma terminal para probarlo:

```powershell
ollama run asistente-innovar
```

¡Listo! Ya tienes el asistente corriendo localmente con sus limitaciones. Te sugerimos realizar pruebas intentando:
* Hacerle preguntas de temas cotidianos (fuera de tópico) para validar que se niegue a responder.
* Comprobar que responde con un tono formal e institucional.

## Próximos pasos: Integración con la Web
Cuando pasemos a la etapa de integrar esto con la interfaz web y Supabase, ya no chatearás desde la terminal. Tu aplicación web o backend hará peticiones en segundo plano a la API de Ollama (que corre por defecto en `http://localhost:11434/api/chat`), pidiéndole que use el modelo `asistente-innovar` que acabas de crear.
