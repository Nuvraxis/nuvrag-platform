import type { ChatbotStatus, DocumentStatus, TicketPriority, TicketStatus } from '@rag/api-client'
import { Badge } from '@rag/ui'
import type { ComponentProps } from 'react'

type Variant = NonNullable<ComponentProps<typeof Badge>['variant']>

const DOCUMENT_VARIANTS: Record<DocumentStatus, Variant> = {
  pending: 'outline',
  processing: 'warning',
  ready: 'success',
  failed: 'destructive',
}

const CHATBOT_VARIANTS: Record<ChatbotStatus, Variant> = {
  active: 'success',
  paused: 'warning',
  archived: 'outline',
}

// Reuses the `success` / `warning` pair added for document status rather than introducing a
// third palette: an unclaimed ticket wants attention, one in hand is progress, and both
// terminal states are quiet.
const TICKET_VARIANTS: Record<TicketStatus, Variant> = {
  open: 'warning',
  pending: 'default',
  resolved: 'success',
  closed: 'outline',
}

const PRIORITY_VARIANTS: Record<TicketPriority, Variant> = {
  low: 'outline',
  normal: 'secondary',
  high: 'warning',
  urgent: 'destructive',
}

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return <Badge variant={DOCUMENT_VARIANTS[status]}>{status}</Badge>
}

export function ChatbotStatusBadge({ status }: { status: ChatbotStatus }) {
  return <Badge variant={CHATBOT_VARIANTS[status]}>{status}</Badge>
}

export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  return <Badge variant={TICKET_VARIANTS[status]}>{status}</Badge>
}

export function TicketPriorityBadge({ priority }: { priority: TicketPriority }) {
  return <Badge variant={PRIORITY_VARIANTS[priority]}>{priority}</Badge>
}
