import type { Fuente } from '../types'

// Respuesta de POST /ia/consultar-guia (backend/app/rag/contrato.py › Respuesta)
export type RespuestaGuia = {
  resultado: string
  encontrada: boolean
  confianza: 'alta' | 'media' | 'baja' | null
  fuentes: Fuente[]
  modelo: string
  version_prompt: string
  modo: string
  puntaje: number | null
  latencia_s: number
}

// En desarrollo, Vite reenvía /ia al backend (vite.config.ts).
export async function consultarGuia(pregunta: string): Promise<RespuestaGuia> {
  let res: Response
  try {
    res = await fetch('/ia/consultar-guia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pregunta }),
    })
  } catch {
    throw new Error('No se pudo conectar con el backend. ¿Está corriendo uvicorn en el puerto 8000?')
  }

  if (!res.ok) {
    const cuerpo = await res.json().catch(() => null)
    const detalle = typeof cuerpo?.detail === 'string' ? cuerpo.detail : null
    if (detalle) {
      throw new Error(detalle)
    }
    if (res.status === 502 || res.status === 504) {
      throw new Error('No se pudo conectar con el backend. ¿Está corriendo uvicorn en el puerto 8000?')
    }
    throw new Error(`El backend respondió con un error (${res.status}).`)
  }
  return res.json()
}
