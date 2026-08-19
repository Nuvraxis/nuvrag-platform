'use client'

import { toast } from '@rag/ui'
import { useEffect, useRef } from 'react'

import type { ActionState } from './action-state'

export interface ActionToastOptions {
  /** Suppress the success toast where the page itself already announces the outcome. */
  success?: boolean
}

/**
 * Announces the result of a Server Action.
 *
 * Fires on the transition into a result, not on every render: `useActionState` hands back a
 * fresh object each submission, so identity is what distinguishes a new outcome from a
 * re-render, and submitting the same form twice must toast twice.
 *
 * With JavaScript disabled none of this runs, which is why the forms keep a `no-js-only`
 * banner carrying the same message.
 */
export function useActionToast<DataT>(
  state: ActionState<DataT>,
  { success = true }: ActionToastOptions = {},
): void {
  const announced = useRef<ActionState<DataT> | null>(null)

  useEffect(() => {
    if (state.status === 'idle' || announced.current === state) return
    announced.current = state

    if (state.status === 'error') {
      toast.error(state.message ?? 'Something went wrong.')
    } else if (success) {
      toast.success(state.message ?? 'Saved.')
    }
  }, [state, success])
}
