'use client'

import { Alert, AlertDescription } from '@rag/ui'
import type { ReactNode, RefObject } from 'react'
import { useActionState } from 'react'

import { type ActionState, idle } from '@/lib/action-state'
import { useActionToast } from '@/lib/use-action-toast'

export interface ActionFormProps {
  action: (previous: ActionState, formData: FormData) => Promise<ActionState>
  children: ReactNode
  className?: string
  /** Off where the change is self-evident on the page and a toast would only repeat it. */
  announceSuccess?: boolean
  /** For controls that submit themselves, such as a select that saves on change. */
  formRef?: RefObject<HTMLFormElement | null>
}

/**
 * A form for the small mutations that live inside a table row or a card footer.
 *
 * It exists so the pages holding them stay Server Components: `useActionState` needs a client
 * boundary, and putting that boundary around the form rather than the page keeps the rows
 * themselves server-rendered. The banner is the fallback for browsers running no JavaScript,
 * where the toast never fires.
 */
export function ActionForm({
  action,
  children,
  className,
  announceSuccess = true,
  formRef,
}: ActionFormProps) {
  const [state, formAction] = useActionState<ActionState, FormData>(action, idle)
  useActionToast(state, { success: announceSuccess })

  return (
    <form ref={formRef} action={formAction} className={className}>
      {children}
      {state.status === 'error' && state.message ? (
        <Alert variant="destructive" role="status" className="no-js-only mt-2">
          <AlertDescription>{state.message}</AlertDescription>
        </Alert>
      ) : null}
    </form>
  )
}
