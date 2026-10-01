export type Role = 'user' | 'assistant'

export type Fuente = {
  seccion: string
  pagina: number
  fuente: string
  fragmento: string
  puntaje: number
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
