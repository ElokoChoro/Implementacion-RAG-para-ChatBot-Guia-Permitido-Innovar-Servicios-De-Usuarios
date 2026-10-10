import type { AdjuntoCargado, Fuente, LimitesAdjunto } from '../types'

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

const SIN_BACKEND = 'No se pudo conectar con el backend. ¿Está corriendo uvicorn en el puerto 8000?'

// Formatos y tope que se usan si /salud no responde: los valores por defecto de config.py.
export const LIMITES_POR_DEFECTO: LimitesAdjunto = { formatos: ['pdf', 'docx'], maxMb: 10 }

// En desarrollo, Vite reenvía /ia al backend (vite.config.ts).
async function pedir(url: string, init: RequestInit): Promise<Response> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new Error(SIN_BACKEND)
  }
  if (!res.ok) {
    const cuerpo = await res.json().catch(() => null)
    const detalle = typeof cuerpo?.detail === 'string' ? cuerpo.detail : null
    if (detalle) {
      throw new Error(detalle)
    }
    if (res.status === 502 || res.status === 504) {
      throw new Error(SIN_BACKEND)
    }
    throw new Error(`El backend respondió con un error (${res.status}).`)
  }
  return res
}

export async function consultarGuia(pregunta: string): Promise<RespuestaGuia> {
  const res = await pedir('/ia/consultar-guia', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pregunta }),
  })
  return res.json()
}

// POST /ia/adjuntos (backend/app/api.py). El navegador pone el Content-Type multipart.
export async function subirAdjunto(archivo: File): Promise<AdjuntoCargado> {
  const datos = new FormData()
  datos.append('archivo', archivo)
  const res = await pedir('/ia/adjuntos', { method: 'POST', body: datos })
  return res.json()
}

// DELETE /ia/adjuntos/{id}. Un 404 quiere decir que ya no estaba: no es un error para quien lo quita.
export async function borrarAdjunto(adjuntoId: string): Promise<void> {
  try {
    await pedir(`/ia/adjuntos/${encodeURIComponent(adjuntoId)}`, { method: 'DELETE' })
  } catch (error) {
    if (!(error instanceof Error && error.message.includes('ya no está disponible'))) {
      throw error
    }
  }
}

// Formatos y tope de los adjuntos según GET /salud; los de por defecto si no responde.
export async function leerLimites(): Promise<LimitesAdjunto> {
  try {
    const salud = await (await pedir('/salud', {})).json()
    const formatos = Array.isArray(salud.formatos_adjunto) ? salud.formatos_adjunto : LIMITES_POR_DEFECTO.formatos
    const maxMb = typeof salud.max_mb_adjunto === 'number' ? salud.max_mb_adjunto : LIMITES_POR_DEFECTO.maxMb
    return { formatos, maxMb }
  } catch {
    return LIMITES_POR_DEFECTO
  }
}
