import type { Conversation } from './types'

export const initialConversations: Conversation[] = [
  {
    id: 'c1',
    title: 'Política de vacaciones',
    preview: '¿Cuántos días corresponden al primer año?',
    updatedAt: 'Hoy',
    messages: [
      {
        id: 'm1',
        role: 'user',
        content: '¿Cuántos días de vacaciones corresponden al primer año?',
        time: '10:12',
      },
      {
        id: 'm2',
        role: 'assistant',
        content:
          'Según la documentación interna, el primer año corresponden 14 días hábiles. A partir del segundo año se suman 2 días adicionales, con un tope de 21.',
        time: '10:12',
      },
      {
        id: 'm3',
        role: 'user',
        content: '¿Se pueden fraccionar en períodos de 5 días?',
        time: '10:14',
      },
      {
        id: 'm4',
        role: 'assistant',
        content:
          'Sí. El mínimo por tramo es de 5 días hábiles, salvo acuerdo previo con el responsable de área. El saldo restante puede tomarse más adelante en el mismo año calendario.',
        time: '10:14',
      },
    ],
  },
  {
    id: 'c2',
    title: 'Onboarding técnico',
    preview: 'Checklist de acceso al entorno de desarrollo',
    updatedAt: 'Ayer',
    messages: [
      {
        id: 'm5',
        role: 'user',
        content: 'Necesito el checklist de acceso al entorno de desarrollo.',
        time: '18:40',
      },
      {
        id: 'm6',
        role: 'assistant',
        content:
          'El onboarding técnico incluye: cuenta de Git, VPN, acceso a Jira, secrets del vault y la guía de setup local. Puedo detallarte cada paso si lo querés.',
        time: '18:40',
      },
    ],
  },
  {
    id: 'c3',
    title: 'SLA de soporte',
    preview: 'Tiempos de respuesta por prioridad',
    updatedAt: 'Lun',
    messages: [
      {
        id: 'm7',
        role: 'user',
        content: '¿Cuáles son los tiempos de respuesta por prioridad?',
        time: '09:05',
      },
      {
        id: 'm8',
        role: 'assistant',
        content:
          'P1: 15 minutos. P2: 2 horas. P3: 8 horas hábiles. P4: 2 días hábiles. Estos valores salen del documento de SLA vigente.',
        time: '09:05',
      },
    ],
  },
]
