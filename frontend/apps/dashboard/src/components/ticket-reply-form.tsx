'use client'

import { Alert, AlertDescription, Field, FieldGroup, Textarea } from '@rag/ui'

import { replyToTicketAction } from '@/lib/actions/tickets'
import { ticketReplySchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'

import { FormField } from './form-field'
import { SubmitButton } from './submit-button'

/**
 * The staff reply composer.
 *
 * Same anatomy as every other form here — `useActionForm` around a Server Action, `FormField`
 * around the control — so it validates before the round trip, reports a 422 back onto the
 * field, and still posts with JavaScript disabled.
 */
export function TicketReplyForm({ ticketId }: { ticketId: string }) {
  const { form, state, formProps } = useActionForm({
    action: replyToTicketAction,
    schema: ticketReplySchema,
    defaultValues: { content: '' },
    resetOnSuccess: true,
  })

  return (
    <form {...formProps}>
      <input type="hidden" name="ticket_id" value={ticketId} />
      <FieldGroup className="gap-3">
        {state.status === 'error' && state.message ? (
          <Alert variant="destructive" role="status" className="no-js-only">
            <AlertDescription>{state.message}</AlertDescription>
          </Alert>
        ) : null}

        <FormField
          control={form.control}
          name="content"
          label="Reply to the visitor"
          description="Nothing is emailed. The visitor reads this when they next open the chat widget."
        >
          {({ field, invalid }) => (
            <Textarea
              {...field}
              id={field.name}
              rows={5}
              placeholder="Write your reply…"
              aria-invalid={invalid}
            />
          )}
        </FormField>

        <Field orientation="horizontal">
          <SubmitButton pendingLabel="Sending…">Send reply</SubmitButton>
        </Field>
      </FieldGroup>
    </form>
  )
}
