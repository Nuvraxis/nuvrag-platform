'use client'

import {
  Alert,
  AlertDescription,
  buttonVariants,
  Card,
  CardContent,
  CardFooter,
  FieldGroup,
} from '@rag/ui'
import Link from 'next/link'

import { createChatbotAction } from '@/lib/actions/chatbots'
import { chatbotSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'

import { ChatbotFields, chatbotDefaults } from './chatbot-fields'
import { SecretKeyNotice } from './secret-key-notice'
import { SubmitButton } from './submit-button'

export function CreateChatbotForm() {
  const { form, state, formProps } = useActionForm({
    action: createChatbotAction,
    schema: chatbotSchema,
    defaultValues: chatbotDefaults(),
    announceSuccess: false,
  })

  // Deliberately no redirect on success: the secret key is returned once and would be lost
  // on navigation, so the user acknowledges it and moves on themselves.
  if (state.status === 'success' && state.data) {
    return (
      <Card>
        <CardContent className="space-y-4">
          <div>
            <h2 className="text-foreground font-medium">{state.data.name} is ready</h2>
            <p className="text-muted-foreground text-sm">
              Public slug <code className="font-mono">{state.data.slug}</code>
            </p>
          </div>
          <SecretKeyNotice secretKey={state.data.secretKey} />
        </CardContent>
        <CardFooter>
          <Link href={`/chatbots/${state.data.id}/documents`} className={buttonVariants()}>
            Upload documents
          </Link>
        </CardFooter>
      </Card>
    )
  }

  return (
    <Card>
      <form {...formProps}>
        <CardContent>
          <FieldGroup>
            {state.status === 'error' && state.message ? (
              <Alert variant="destructive" role="status" className="no-js-only">
                <AlertDescription>{state.message}</AlertDescription>
              </Alert>
            ) : null}
            <ChatbotFields control={form.control} />
          </FieldGroup>
        </CardContent>
        <CardFooter>
          <Link href="/chatbots" className={buttonVariants({ variant: 'secondary' })}>
            Cancel
          </Link>
          <SubmitButton pendingLabel="Creating…">Create chatbot</SubmitButton>
        </CardFooter>
      </form>
    </Card>
  )
}
