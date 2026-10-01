import { IconChat, IconPlus, IconSearch, IconSpark } from '../icons'
import type { Conversation } from '../types'

type SidebarProps = {
  conversations: Conversation[]
  activeId: string
  query: string
  onQueryChange: (value: string) => void
  onSelect: (id: string) => void
  onNewChat: () => void
}

export function Sidebar({
  conversations,
  activeId,
  query,
  onQueryChange,
  onSelect,
  onNewChat,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <IconSpark />
        </span>
        <div>
          <p className="brand-name">RAG ChatBot</p>
          <p className="brand-sub">Guía Permitido Innovar</p>
        </div>
      </div>

      <button className="new-chat" type="button" onClick={onNewChat}>
        <IconPlus />
        Nueva conversación
      </button>

      <label className="search">
        <IconSearch />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Buscar chats"
          aria-label="Buscar chats"
        />
      </label>

      <p className="section-label">Recientes</p>
      <nav className="chat-list" aria-label="Conversaciones">
        {conversations.map((conversation) => (
          <button
            key={conversation.id}
            type="button"
            className={conversation.id === activeId ? 'chat-item active' : 'chat-item'}
            onClick={() => onSelect(conversation.id)}
          >
            <span className="chat-icon">
              <IconChat />
            </span>
            <span className="chat-meta">
              <span className="chat-title-row">
                <span className="chat-title">{conversation.title}</span>
                <span className="chat-time">{conversation.updatedAt}</span>
              </span>
              <span className="chat-preview">{conversation.preview}</span>
            </span>
          </button>
        ))}
        {conversations.length === 0 && (
          <p className="empty-list">No hay conversaciones con ese filtro.</p>
        )}
      </nav>

      <div className="sidebar-footer">
        <div className="avatar">AC</div>
        <div>
          <p className="user-name">Ana Costa</p>
          <p className="user-role">Equipo interno</p>
        </div>
      </div>
    </aside>
  )
}
