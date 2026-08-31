'use client'

import type { MemoryCalibration } from '@rag/api-client'
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

import { recalibrateMemoryAction } from '@/lib/actions/chatbots'
import { type ActionState, idle } from '@/lib/action-state'
import { useActionToast } from '@/lib/use-action-toast'

import { SubmitButton } from './submit-button'

/**
 * Its own panel rather than a button inside the settings form, for the plain reason that a
 * form cannot nest inside another. It also does something different in kind: saving settings
 * writes a row, and this calls the chatbot's embedding provider.
 */
export function RecalibrateMemoryPanel({
  chatbotId,
  calibration,
}: {
  chatbotId: string
  calibration: MemoryCalibration
}) {
  const [state, formAction] = useActionState<ActionState, FormData>(recalibrateMemoryAction, idle)
  useActionToast(state)

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>Memory recall threshold</CardTitle>
          <CardDescription>
            How close a remembered note has to be to the visitor&apos;s question is measured
            against this chatbot&apos;s own embedding model, because the numbers a model returns
            are a property of that model. It happens by itself the first time a returning visitor
            writes in, and again whenever the embedding model changes. Measure it now if you
            would rather not wait.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {state.status === 'error' && state.message ? (
          <Alert variant="destructive" role="status" className="no-js-only">
            <AlertDescription>{state.message}</AlertDescription>
          </Alert>
        ) : null}

        {calibration.source === 'override' ? (
          <Alert role="status">
            <AlertDescription>
              A threshold you set is in force, so measuring will not change what gets recalled.
              Clear the recall threshold field above to go back to the measured value.
            </AlertDescription>
          </Alert>
        ) : null}

        <form action={formAction}>
          <input type="hidden" name="chatbot_id" value={chatbotId} />
          <SubmitButton variant="secondary" pendingLabel="Measuring…">
            Recalibrate now
          </SubmitButton>
        </form>
      </CardContent>
    </Card>
  )
}
