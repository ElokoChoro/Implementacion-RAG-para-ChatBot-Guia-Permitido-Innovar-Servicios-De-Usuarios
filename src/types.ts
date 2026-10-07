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

export type Conversation = {
  id: string
  title: string
  preview: string
  updatedAt: string
  messages: Message[]
}
