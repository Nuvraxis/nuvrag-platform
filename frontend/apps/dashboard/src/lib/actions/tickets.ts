'use server'

import type { TicketPriority, TicketStatus, TicketUpdate } from '@rag/api-client'
import { TICKET_PRIORITIES, TICKET_STATUSES } from '@rag/types'
import { revalidatePath } from 'next/cache'

import { type ActionState, failed, fromError, succeeded } from '@/lib/action-state'
import { authenticatedApi } from '@/lib/api'
import { text } from '@/lib/form'

const TICKETS_PATH = '/tickets'

function detailPath(ticketId: string): string {
  return `${TICKETS_PATH}/${ticketId}`
}

function status(formData: FormData, name: string): TicketStatus | null {
  const value = text(formData, name)
  return (TICKET_STATUSES as readonly string[]).includes(value) ? (value as TicketStatus) : null
}

function priority(formData: FormData, name: string): TicketPriority | null {
  const value = text(formData, name)
  return (TICKET_PRIORITIES as readonly string[]).includes(value) ? (value as TicketPriority) : null
}

/**
 * The three controls on the detail page share one action.
 *
 * Each posts a hidden `ticket_id` plus exactly one changed field, so the body sent to the API
 * only ever carries what the control the user touched is responsible for — a status change
 * never silently restates the assignment alongside it.
 */
async function patch(
  ticketId: string,
  // `unassign` carries a server-side default, but the generator emits every defaulted
  // non-nullable field as required — as it already does for `TokenPair.token_type` — so it
  // is filled in below rather than left to the caller of each control.
  body: Omit<TicketUpdate, 'unassign'> & { unassign?: boolean },
  message: string,
): Promise<ActionState> {
  const api = await authenticatedApi()
  try {
    await api.updateTicket(ticketId, { unassign: false, ...body })
    revalidatePath(TICKETS_PATH)
    revalidatePath(detailPath(ticketId))
    return succeeded(message)
  } catch (error) {
    return fromError(error)
  }
}

export async function updateTicketStatusAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = text(formData, 'ticket_id')
  const next = status(formData, 'status')
  if (!ticketId || !next) return failed('That is not a status a ticket can be in.')

  return patch(ticketId, { status: next }, `Ticket marked ${next}.`)
}

export async function updateTicketPriorityAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = text(formData, 'ticket_id')
  const next = priority(formData, 'priority')
  if (!ticketId || !next) return failed('That is not a priority a ticket can have.')

  return patch(ticketId, { priority: next }, `Priority set to ${next}.`)
}

/**
 * The empty option means "nobody", which is a real choice rather than a missing one — hence
 * the explicit `unassign` flag. The API cannot tell an omitted nullable field from one set
 * to null, so saying so is the only way to hand a ticket back to the queue.
 */
export async function assignTicketAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = text(formData, 'ticket_id')
  if (!ticketId) return failed('That ticket could not be identified.')

  const assignee = text(formData, 'assigned_to')
  if (!assignee) {
    return patch(ticketId, { unassign: true }, 'Ticket returned to the queue.')
  }
  return patch(ticketId, { assigned_to: assignee }, 'Ticket assigned.')
}

export async function replyToTicketAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const ticketId = text(formData, 'ticket_id')
  if (!ticketId) return failed('That ticket could not be identified.')

  const content = text(formData, 'content')
  if (!content) {
    return failed('Write a reply before sending.', { content: 'A reply cannot be empty.' })
  }

  const api = await authenticatedApi()
  try {
    await api.replyToTicket(ticketId, { content })
    revalidatePath(TICKETS_PATH)
    revalidatePath(detailPath(ticketId))
    // Said plainly: nothing is emailed, and the visitor sees this when they return to the
    // widget. Promising a notification the platform cannot send would be worse than silence.
    return succeeded('Reply added. The visitor sees it next time they open the chat.')
  } catch (error) {
    return fromError(error)
  }
}
