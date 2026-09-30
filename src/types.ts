export type Role = 'user' | 'assistant'

export type Message = {
  id: string
  role: Role
  content: string
  time: string
}

export type Conversation = {
  id: string
  title: string
  preview: string
  updatedAt: string
  messages: Message[]
}
