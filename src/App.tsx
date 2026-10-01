import { useMemo, useState } from 'react'
import { Chat } from './components/Chat'
import { Sidebar } from './components/Sidebar'
import { consultarGuia } from './lib/rag'
import type { Conversation, Message } from './types'
import './App.css'

function createEmptyConversation(): Conversation {
  return {
    id: crypto.randomUUID(),
    title: 'Nueva conversación',
    preview: 'Pregúntale a la guía…',
    updatedAt: 'Ahora',
    messages: [],
  }
}

function now() {
  return new Date().toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })
}

export default function App() {
  const [conversations, setConversations] = useState(() => [createEmptyConversation()])
  const [activeId, setActiveId] = useState(conversations[0].id)
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const filtered = useMemo(
    () =>
      conversations.filter((item) =>
        `${item.title} ${item.preview}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [conversations, query],
  )

  const active = conversations.find((item) => item.id === activeId) ?? conversations[0]

  const waiting = active.messages.some((message) => message.status === 'pending')

  function updateMessage(conversationId: string, messageId: string, patch: Partial<Message>) {
    setConversations((current) =>
      current.map((conversation) =>
        conversation.id !== conversationId
          ? conversation
          : {
              ...conversation,
              messages: conversation.messages.map((message) =>
                message.id === messageId ? { ...message, ...patch } : message,
              ),
            },
      ),
    )
  }

  async function sendMessage() {
    const text = draft.trim()
    if (!text || !active || waiting) {
      return
    }

    const conversationId = active.id
    const replyId = crypto.randomUUID()

    setConversations((current) =>
      current.map((conversation) => {
        if (conversation.id !== conversationId) {
          return conversation
        }

        return {
          ...conversation,
          title: conversation.messages.length === 0 ? text.slice(0, 42) : conversation.title,
          preview: text,
          updatedAt: 'Ahora',
          messages: [
            ...conversation.messages,
            { id: crypto.randomUUID(), role: 'user', content: text, time: now() },
            {
              id: replyId,
              role: 'assistant',
              content: 'Buscando en la guía… La primera pregunta carga los modelos y puede tardar unos minutos.',
              time: now(),
              status: 'pending',
            },
          ],
        }
      }),
    )
    setDraft('')

    try {
      const respuesta = await consultarGuia(text)
      updateMessage(conversationId, replyId, {
        content: respuesta.resultado,
        time: now(),
        status: undefined,
        fuentes: respuesta.fuentes,
        confianza: respuesta.confianza,
      })
    } catch (error) {
      updateMessage(conversationId, replyId, {
        content: error instanceof Error ? error.message : 'Error desconocido.',
        time: now(),
        status: 'error',
      })
    }
  }

  function startNewChat() {
    const next = createEmptyConversation()
    setConversations((current) => [next, ...current])
    setActiveId(next.id)
    setDraft('')
    setSidebarOpen(false)
  }

  return (
    <div className={sidebarOpen ? 'app sidebar-open' : 'app'}>
      <Sidebar
        conversations={filtered}
        activeId={active.id}
        query={query}
        onQueryChange={setQuery}
        onSelect={(id) => {
          setActiveId(id)
          setSidebarOpen(false)
        }}
        onNewChat={startNewChat}
      />
      <button
        className="backdrop"
        type="button"
        aria-label="Cerrar menú"
        onClick={() => setSidebarOpen(false)}
      />
      <Chat
        conversation={active}
        draft={draft}
        onDraftChange={setDraft}
        onSend={sendMessage}
        waiting={waiting}
        onToggleSidebar={() => setSidebarOpen(true)}
      />
    </div>
  )
}
