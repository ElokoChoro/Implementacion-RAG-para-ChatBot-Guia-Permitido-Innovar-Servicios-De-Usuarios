export type Role = 'user' | 'assistant'

export type Fuente = {
  seccion: string
  pagina: number
  fuente: string
  fragmento: string
  puntaje: number
}

// Respuesta de POST /ia/adjuntos (backend/app/adjuntos/tipos.py › AdjuntoCargado)
export type AdjuntoCargado = {
  adjunto_id: string
  nombre: string
  formato: string
  paginas: number | null
  fragmentos: number
  caracteres: number
  reemplazos: Record<string, number>
  expira_en_s: number
  modo: string
  latencia_s: number
}

export type Message = {
  id: string
  role: Role
  content: string
  time: string
  status?: 'pending' | 'error'
  fuentes?: Fuente[]
  confianza?: 'alta' | 'media' | 'baja' | null
}

// Un adjunto subido en la conversación. `vence` es la hora (Date.now()) en que el backend lo descarta.
export type Adjunto = {
  datos: AdjuntoCargado
  vence: number
}

// Formatos (sin punto) y tamaño máximo en MB que acepta POST /ia/adjuntos, según GET /salud.
export type LimitesAdjunto = {
  formatos: string[]
  maxMb: number
}

export type Conversation = {
  id: string
  title: string
  preview: string
  updatedAt: string
  messages: Message[]
  adjuntos?: Adjunto[]
  subiendo?: string | null
}
