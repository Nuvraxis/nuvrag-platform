'use client'

import type { Chatbot, TicketStatus } from '@rag/api-client'
import { TICKET_STATUSES } from '@rag/types'
import { Button, Card, CardContent, Field, FieldLabel, NativeSelect } from '@rag/ui'
import { useRef } from 'react'

export interface TicketFiltersProps {
  chatbots: Chatbot[]
  status?: TicketStatus
  chatbotId?: string
}

/**
 * Chatbot and status filters, as a plain GET form.
 *
 * No Server Action and no client state: the filters *are* the URL, so a filtered queue is a
 * link someone can send a colleague, and the page re-renders on the server with the same
 * query it would have run anyway. It submits on change where JavaScript is running and via
 * the button beside it where it is not.
 */
export function TicketFilters({ chatbots, status, chatbotId }: TicketFiltersProps) {
  const formRef = useRef<HTMLFormElement>(null)
  const submit = () => formRef.current?.requestSubmit()

  return (
    <Card>
      <CardContent>
        <form
          ref={formRef}
          method="get"
          action="/tickets"
          className="flex flex-wrap items-end gap-4"
        >
          <Field className="w-56">
            <FieldLabel htmlFor="filter-chatbot">Chatbot</FieldLabel>
            <NativeSelect
              id="filter-chatbot"
              name="chatbot_id"
              defaultValue={chatbotId ?? ''}
              onChange={submit}
            >
              <option value="">All chatbots</option>
              {chatbots.map((chatbot) => (
                <option key={chatbot.id} value={chatbot.id}>
                  {chatbot.name}
                </option>
              ))}
            </NativeSelect>
          </Field>

          <Field className="w-44">
            <FieldLabel htmlFor="filter-status">Status</FieldLabel>
            <NativeSelect
              id="filter-status"
              name="status"
              defaultValue={status ?? ''}
              onChange={submit}
            >
              <option value="">Any status</option>
              {TICKET_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </NativeSelect>
          </Field>

          <Button type="submit" variant="secondary" size="sm" className="no-js-only">
            Apply filters
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
