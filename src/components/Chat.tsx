import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react'
import { IconAttach, IconDots, IconMenu, IconSend, IconSpark } from '../icons'
import type { Conversation } from '../types'

type ChatProps = {
  conversation: Conversation
  draft: string
  onDraftChange: (value: string) => void
  onSend: () => void
  onToggleSidebar: () => void
}

export function Chat({
  conversation,
  draft,
  onDraftChange,
  onSend,
  onToggleSidebar,
}: ChatProps) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conversation.messages])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onSend()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSend()
    }
  }

  const isEmpty = conversation.messages.length === 0

  return (
    <section className="chat">
      <header className="chat-header">
        <button className="icon-btn mobile-only" type="button" onClick={onToggleSidebar} aria-label="Abrir menú">
          <IconMenu />
        </button>
        <div>
          <h1>{conversation.title}</h1>
          <p>Respuestas basadas en documentos internos</p>
        </div>
        <button className="icon-btn" type="button" aria-label="Más opciones">
          <IconDots />
        </button>
      </header>

      <div className="messages" role="log" aria-live="polite">
        {isEmpty ? (
          <div className="welcome">
            <span className="welcome-icon">
              <IconSpark size={28} />
            </span>
            <h2>¿En qué te ayudo hoy?</h2>
            <p>Consultá políticas, procedimientos o documentación de la empresa.</p>
            <div className="suggestions">
              <button type="button" onClick={() => onDraftChange('Resumí la política de vacaciones.')}>
                Política de vacaciones
              </button>
              <button type="button" onClick={() => onDraftChange('¿Cuál es el SLA de un incidente P1?')}>
                SLA de incidentes
              </button>
              <button type="button" onClick={() => onDraftChange('Pasos del onboarding técnico')}>
                Onboarding técnico
              </button>
            </div>
          </div>
        ) : (
          conversation.messages.map((message) => (
            <article key={message.id} className={`bubble-row ${message.role}`}>
              <div className={`bubble ${message.role}`}>
                {message.role === 'assistant' && (
                  <span className="bubble-label">Asistente</span>
                )}
                <p>{message.content}</p>
                <time>{message.time}</time>
              </div>
            </article>
          ))
        )}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={handleSubmit}>
        <button className="icon-btn" type="button" aria-label="Adjuntar archivo">
          <IconAttach />
        </button>
        <textarea
          rows={1}
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Escribí tu pregunta…"
          aria-label="Mensaje"
        />
        <button className="send" type="submit" disabled={!draft.trim()} aria-label="Enviar">
          <IconSend />
        </button>
      </form>
    </section>
  )
}
