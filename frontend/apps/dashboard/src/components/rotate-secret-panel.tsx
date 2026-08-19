'use client'

import {
  Alert,
  AlertDescription,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@rag/ui'
import { useActionState } from 'react'

import { type ActionState, idle } from '@/lib/action-state'
import { useActionToast } from '@/lib/use-action-toast'
import { type RotatedSecret, rotateSecretAction } from '@/lib/actions/chatbots'

import { ConfirmSubmit } from './confirm-submit'
import { SecretKeyNotice } from './secret-key-notice'

export function RotateSecretPanel({ chatbotId }: { chatbotId: string }) {
  const [state, formAction] = useActionState<ActionState<RotatedSecret>, FormData>(
    rotateSecretAction,
    idle,
  )
  useActionToast(state)

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>Secret key</CardTitle>
          <CardDescription>
            Rotating takes effect immediately; anything still using the previous key stops working.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {state.status === 'error' && state.message ? (
          <Alert variant="destructive" role="status" className="no-js-only">
            <AlertDescription>{state.message}</AlertDescription>
          </Alert>
        ) : null}

        {state.status === 'success' && state.data ? (
          <SecretKeyNotice secretKey={state.data.secretKey} />
        ) : null}

        <form action={formAction}>
          <input type="hidden" name="chatbot_id" value={chatbotId} />
          <ConfirmSubmit
            variant="secondary"
            confirmTitle="Rotate the secret key?"
            confirmDescription="The current one stops working straight away, so anything signing requests with it will start failing until it is replaced."
            confirmLabel="Rotate key"
            pendingLabel="Rotating…"
          >
            Rotate secret key
          </ConfirmSubmit>
        </form>
      </CardContent>
    </Card>
  )
}
