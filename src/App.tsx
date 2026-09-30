import { useMemo, useState } from 'react'
import { Chat } from './components/Chat'
import { Sidebar } from './components/Sidebar'
import { initialConversations } from './data'
import type { Conversation } from './types'
import './App.css'

function createEmptyConversation(): Conversation {
  return {
    id: crypto.randomUUID(),
    title: 'Nueva conversación',
    preview: 'Empezá a escribir…',
    updatedAt: 'Ahora',
    messages: [],
  }
}

export default function App() {
  const [conversations, setConversations] = useState(initialConversations)
  const [activeId, setActiveId] = useState(initialConversations[0].id)
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

  function sendMessage() {
    const text = draft.trim()
    if (!text || !active) {
      return
    }

    const time = new Date().toLocaleTimeString('es-AR', {
      hour: '2-digit',
      minute: '2-digit',
    })

    setConversations((current) =>
      current.map((conversation) => {
        if (conversation.id !== active.id) {
          return conversation
        }

        return {
          ...conversation,
          title: conversation.messages.length === 0 ? text.slice(0, 42) : conversation.title,
          preview: text,
          updatedAt: 'Ahora',
          messages: [
            ...conversation.messages,
            { id: crypto.randomUUID(), role: 'user', content: text, time },
            {
              id: crypto.randomUUID(),
              role: 'assistant',
              content:
                'Esta es una respuesta de demostración. Cuando conectemos el motor RAG, acá van a aparecer citas de tus documentos.',
              time,
            },
          ],
        }
      }),
    )
    setDraft('')
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
        onToggleSidebar={() => setSidebarOpen(true)}
      />
    </div>
  )
}
