'use client'

import type { Chatbot, MemoryCalibration } from '@rag/api-client'
import {
  Alert,
  AlertDescription,
  Card,
  CardContent,
  CardFooter,
  FieldGroup,
  NativeSelect,
} from '@rag/ui'
import { CHATBOT_STATUSES } from '@rag/types'

import { updateChatbotAction } from '@/lib/actions/chatbots'
import { chatbotSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'

import { ChatbotFields, chatbotDefaults } from './chatbot-fields'
import { FormField } from './form-field'
import { SubmitButton } from './submit-button'

const STATUS_HINT: Record<string, string> = {
  active: 'Answers questions from the widget.',
  paused:
    'The widget stops appearing on your sites — no launcher, nothing. The embed snippet can stay in place; it comes back when this is active again.',
  archived:
    'The widget stops appearing, and the chatbot is out of the way day to day. Documents, conversations and settings are all kept.',
}

export function ChatbotSettingsForm({
  chatbot,
  calibration,
}: {
  chatbot: Chatbot
  calibration: MemoryCalibration
}) {
  const { form, state, formProps } = useActionForm({
    action: updateChatbotAction,
    schema: chatbotSchema,
    defaultValues: chatbotDefaults(chatbot),
  })

  const status = form.watch('status')

  return (
    <Card>
      <form {...formProps}>
        <input type="hidden" name="chatbot_id" value={chatbot.id} />
        <CardContent>
          <FieldGroup>
            {state.message ? (
              <Alert
                variant={state.status === 'error' ? 'destructive' : 'default'}
                role="status"
                className="no-js-only"
              >
                <AlertDescription>{state.message}</AlertDescription>
              </Alert>
            ) : null}

            <ChatbotFields
              control={form.control}
              usage={chatbot.usage}
              calibration={calibration}
            />

            <FormField
              control={form.control}
              name="status"
              label="Status"
              description={status ? STATUS_HINT[status] : undefined}
            >
              {({ field, invalid }) => (
                <NativeSelect {...field} id={field.name} aria-invalid={invalid}>
                  {CHATBOT_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </FormField>
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <SubmitButton pendingLabel="Saving…">Save changes</SubmitButton>
        </CardFooter>
      </form>
    </Card>
  )
}
