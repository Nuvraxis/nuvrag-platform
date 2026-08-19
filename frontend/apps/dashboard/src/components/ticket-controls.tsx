'use client'

import type { Ticket, User } from '@rag/api-client'
import { TICKET_PRIORITIES, TICKET_STATUSES } from '@rag/types'
import { Field, FieldLabel, NativeSelect } from '@rag/ui'
import { useRef } from 'react'

import {
  assignTicketAction,
  updateTicketPriorityAction,
  updateTicketStatusAction,
} from '@/lib/actions/tickets'

import { ActionForm } from './action-form'
import { SubmitButton } from './submit-button'

export interface TicketControlsProps {
  ticket: Ticket
  members: User[]
}

/**
 * Status, priority and assignment, each its own small Server Action form.
 *
 * All three are real `<select>` elements inside real forms: they submit on change where
 * JavaScript is running, and the visible submit button beside them is what makes them work
 * without it — the same bargain `MemberRowActions` strikes. A Radix listbox would render
 * nothing usable in that state and take the control with it.
 */
export function TicketControls({ ticket, members }: TicketControlsProps) {
  const statusForm = useRef<HTMLFormElement>(null)
  const priorityForm = useRef<HTMLFormElement>(null)
  const assignForm = useRef<HTMLFormElement>(null)

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <ActionForm formRef={statusForm} action={updateTicketStatusAction} announceSuccess={false}>
        <input type="hidden" name="ticket_id" value={ticket.id} />
        <Field>
          <FieldLabel htmlFor="ticket-status">Status</FieldLabel>
          <NativeSelect
            id="ticket-status"
            name="status"
            defaultValue={ticket.status}
            onChange={() => statusForm.current?.requestSubmit()}
          >
            {TICKET_STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <SubmitButton variant="secondary" size="sm" className="no-js-only mt-2">
          Save status
        </SubmitButton>
      </ActionForm>

      <ActionForm
        formRef={priorityForm}
        action={updateTicketPriorityAction}
        announceSuccess={false}
      >
        <input type="hidden" name="ticket_id" value={ticket.id} />
        <Field>
          <FieldLabel htmlFor="ticket-priority">Priority</FieldLabel>
          <NativeSelect
            id="ticket-priority"
            name="priority"
            defaultValue={ticket.priority}
            onChange={() => priorityForm.current?.requestSubmit()}
          >
            {TICKET_PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <SubmitButton variant="secondary" size="sm" className="no-js-only mt-2">
          Save priority
        </SubmitButton>
      </ActionForm>

      <ActionForm formRef={assignForm} action={assignTicketAction} announceSuccess={false}>
        <input type="hidden" name="ticket_id" value={ticket.id} />
        <Field>
          <FieldLabel htmlFor="ticket-assignee">Assigned to</FieldLabel>
          <NativeSelect
            id="ticket-assignee"
            name="assigned_to"
            defaultValue={ticket.assigned_to ?? ''}
            onChange={() => assignForm.current?.requestSubmit()}
          >
            {/* An empty value is a deliberate choice — hand the ticket back to the queue —
                rather than an absent one, which is why the action sends `unassign`. */}
            <option value="">Unassigned</option>
            {members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.full_name ?? member.email}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <SubmitButton variant="secondary" size="sm" className="no-js-only mt-2">
          Save assignee
        </SubmitButton>
      </ActionForm>
    </div>
  )
}
