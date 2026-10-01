import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react'
import { IconAttach, IconDots, IconMenu, IconSend, IconSpark } from '../icons'
import type { Conversation } from '../types'

type ChatProps = {
  conversation: Conversation
  draft: string
  onDraftChange: (value: string) => void
  onSend: () => void
  onToggleSidebar: () => void
  waiting: boolean
}

const SUGERENCIAS = [
  '¿Qué es un mapa de momentos críticos?',
  '¿Cómo se hace un plano del servicio?',
  '¿Qué etapas tiene la guía?',
]

export function Chat({
  conversation,
  draft,
  onDraftChange,
  onSend,
  onToggleSidebar,
  waiting,
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
          <p>Respuestas basadas en la guía Permitido Innovar</p>
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
            <p>
              Pregunta sobre «¿Cómo podemos innovar en los servicios públicos desde la experiencia
              usuaria?». Cada respuesta cita la sección y la página de la guía.
            </p>
            <div className="suggestions">
              {SUGERENCIAS.map((sugerencia) => (
                <button key={sugerencia} type="button" onClick={() => onDraftChange(sugerencia)}>
                  {sugerencia}
                </button>
              ))}
            </div>
          </div>
        ) : (
          conversation.messages.map((message) => (
            <article key={message.id} className={`bubble-row ${message.role}`}>
              <div className={`bubble ${message.role} ${message.status ?? ''}`}>
                {message.role === 'assistant' && (
                  <span className="bubble-label">
                    Asistente
                    {message.confianza && (
                      <span className={`confidence ${message.confianza}`}>
                        confianza {message.confianza}
                      </span>
                    )}
                  </span>
                )}
                <p>{message.content}</p>
                {message.fuentes && message.fuentes.length > 0 && (
                  <ul className="sources" aria-label="Fuentes">
                    {message.fuentes.map((fuente, index) => (
                      <li key={`${fuente.fuente}-${index}`} title={fuente.fragmento}>
                        {fuente.fuente}
                      </li>
                    ))}
                  </ul>
                )}
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
          placeholder={waiting ? 'Esperando la respuesta…' : 'Escribe tu pregunta…'}
          aria-label="Mensaje"
        />
        <button className="send" type="submit" disabled={!draft.trim() || waiting} aria-label="Enviar">
          <IconSend />
        </button>
      </form>
    </section>
  )
}
