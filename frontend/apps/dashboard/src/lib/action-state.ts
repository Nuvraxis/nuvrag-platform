import { ApiError, ApiUnreachableError } from '@rag/api-client'

/** Shared shape for every `useActionState` form in the dashboard. */
export interface ActionState<DataT = undefined> {
  status: 'idle' | 'error' | 'success'
  message?: string
  /** Keyed by the field name the API reported, which matches the form input's name. */
  fieldErrors?: Record<string, string>
  data?: DataT
}

export const idle: ActionState<never> = { status: 'idle' }

export function failed(message: string, fieldErrors?: Record<string, string>): ActionState<never> {
  return { status: 'error', message, fieldErrors }
}

export function succeeded<DataT>(message: string, data?: DataT): ActionState<DataT> {
  return { status: 'success', message, data }
}

/**
 * Turns whatever an action threw into something a form can render.
 *
 * A 422 carries per-field messages, so those are surfaced next to their inputs and the
 * banner stays generic. Anything else is a single message.
 */
export function fromError(error: unknown): ActionState<never> {
  if (error instanceof ApiError) {
    const fieldErrors = error.toFieldMap()
    if (Object.keys(fieldErrors).length > 0) {
      return failed('Please correct the highlighted fields.', fieldErrors)
    }
    if (error.isUnauthorized) {
      // The proxy refreshes tokens ahead of every request, so reaching here means the
      // session is genuinely finished rather than merely stale.
      return failed('Your session has ended. Sign in again to continue.')
    }
    return failed(error.message)
  }

  if (error instanceof ApiUnreachableError) {
    return failed('The API is not reachable. Check that it is running and try again.')
  }

  return failed('Something went wrong. Please try again.')
}
