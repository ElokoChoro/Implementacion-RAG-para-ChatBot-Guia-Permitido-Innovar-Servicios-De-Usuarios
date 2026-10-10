import { useEffect, useRef, type ChangeEvent, type FormEvent, type KeyboardEvent } from 'react'
import { IconAttach, IconClose, IconMenu, IconSend, IconSpark } from '../icons'
import { aceptados, nombresFormatos } from '../lib/adjuntos'
import type { Conversation, LimitesAdjunto } from '../types'

type ChatProps = {
  conversation: Conversation
  draft: string
  onDraftChange: (value: string) => void
  onSend: () => void
  onAttach: (archivo: File) => void
  onRemoveAttachment: (adjuntoId: string) => void
  onToggleSidebar: () => void
  limites: LimitesAdjunto
  ahora: number
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
  onAttach,
  onRemoveAttachment,
  onToggleSidebar,
  limites,
  ahora,
  waiting,
}: ChatProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

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

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const archivo = event.target.files?.[0]
    event.target.value = '' // para poder volver a elegir el mismo archivo
    if (archivo) {
      onAttach(archivo)
    }
  }

  const isEmpty = conversation.messages.length === 0
  const adjuntos = conversation.adjuntos ?? []
  const subiendo = conversation.subiendo ?? null
  const formatos = nombresFormatos(limites.formatos)

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

      <div className="composer-area">
        {(adjuntos.length > 0 || subiendo) && (
          <ul className="attachments" aria-label="Documentos adjuntos" aria-live="polite">
            {adjuntos.map(({ datos, vence }) => {
              const vencido = ahora >= vence
              return (
                <li key={datos.adjunto_id} className={vencido ? 'attachment expired' : 'attachment'}>
                  <span className="attachment-name">{datos.nombre}</span>
                  {vencido && <span className="attachment-note">venció: vuelve a subirlo</span>}
                  <button
                    type="button"
                    onClick={() => onRemoveAttachment(datos.adjunto_id)}
                    aria-label={`Quitar ${datos.nombre}`}
                  >
                    <IconClose />
                  </button>
                </li>
              )
            })}
            {subiendo && (
              <li className="attachment pending">
                <span className="attachment-name">Leyendo {subiendo}…</span>
              </li>
            )}
          </ul>
        )}
        <form className="composer" onSubmit={handleSubmit}>
          <input
            ref={fileRef}
            type="file"
            accept={aceptados(limites.formatos)}
            onChange={handleFile}
            hidden
          />
          <button
            className="icon-btn"
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={subiendo !== null || waiting}
            aria-label={`Adjuntar archivo (${formatos})`}
            title={`Adjuntar archivo (${formatos}, hasta ${limites.maxMb} MB)`}
          >
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
      </div>
    </section>
  )
}
