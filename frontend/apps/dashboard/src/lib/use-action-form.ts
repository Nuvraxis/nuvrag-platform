'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { type FormEvent, type RefObject, useActionState, useEffect, useRef } from 'react'
import {
  type DefaultValues,
  type FieldValues,
  type Path,
  type UseFormReturn,
  useForm,
} from 'react-hook-form'
import type { ZodType } from 'zod'

import { type ActionState, idle } from './action-state'
import { useActionToast } from './use-action-toast'

export interface UseActionFormOptions<Values extends FieldValues, Parsed, DataT> {
  action: (previous: ActionState<DataT>, formData: FormData) => Promise<ActionState<DataT>>
  /** `Values` is the schema's *input*: what the inputs hold, before any coercion. */
  schema: ZodType<Parsed, Values>
  defaultValues: DefaultValues<Values>
  /** Off where the page itself already announces the outcome and a toast would repeat it. */
  announceSuccess?: boolean
  /**
   * Empties the fields once the action succeeds. React does this by itself for a form it
   * submitted whose inputs are uncontrolled; these are controlled by React Hook Form, so a
   * form meant to be used repeatedly has to ask.
   */
  resetOnSuccess?: boolean
}

export interface ActionForm<Values extends FieldValues, Parsed, DataT> {
  form: UseFormReturn<Values, unknown, Parsed>
  state: ActionState<DataT>
  /** Spread onto the `<form>` element: it carries the action, the guard and the ref. */
  formProps: {
    ref: RefObject<HTMLFormElement | null>
    action: (formData: FormData) => void
    onSubmit: (event: FormEvent<HTMLFormElement>) => void
    noValidate: true
  }
}

/**
 * One Server Action form: React Hook Form for the fields, `useActionState` for the result.
 *
 * The two are joined by leaving the submission itself to React. The `action` prop stays on
 * the element, so `useFormStatus` still reports pending and a browser with JavaScript
 * disabled still posts the form; the `onSubmit` guard runs first and cancels the action when
 * the values do not satisfy the schema. React honours `preventDefault` here and puts the
 * submitter back, so a rejected submit costs nothing but the check.
 *
 * The verdict comes from `safeParse` rather than from awaiting `handleSubmit`, because it has
 * to be reached synchronously: an `await` would land after the event was handled and the
 * request would already be away. Only once the answer is "no" does the event go to
 * `handleSubmit`, which cancels it on its first line and then owns everything that follows.
 */
export function useActionForm<Values extends FieldValues, Parsed, DataT = undefined>({
  action,
  schema,
  defaultValues,
  announceSuccess = true,
  resetOnSuccess = false,
}: UseActionFormOptions<Values, Parsed, DataT>): ActionForm<Values, Parsed, DataT> {
  const [state, formAction] = useActionState<ActionState<DataT>, FormData>(action, idle)
  const formRef = useRef<HTMLFormElement>(null)

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(schema),
    defaultValues,
    // Nothing is complained about until a field has been visited, and from then on it keeps
    // up as the user types: a message never appears before there was a chance to get it
    // right, and never lingers once it has been.
    mode: 'onTouched',
  })

  useActionToast(state, { success: announceSuccess })

  const reported = useRef<ActionState<DataT> | null>(null)
  useEffect(() => {
    // `useActionState` returns a fresh object per submission, so identity is what separates a
    // new result from a re-render — the same test `useActionToast` makes.
    if (reported.current === state) return
    reported.current = state

    if (state.status === 'success' && resetOnSuccess) {
      form.reset()
      return
    }

    restoreSelects(formRef.current, (name) => form.getValues(name as Path<Values>))

    if (state.status === 'success') return

    let first: Path<Values> | undefined
    for (const [name, message] of Object.entries(state.fieldErrors ?? {})) {
      const field = fieldNameFor<Values>(name, defaultValues)
      form.setError(field, { type: 'server', message })
      first ??= field
    }
    if (first) form.setFocus(first)
    // `defaultValues` is a literal at every call site and would change identity on every
    // render, which would re-announce a result the user has already seen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, form, resetOnSuccess])

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    if (schema.safeParse(form.getValues()).success) return

    // Hand the event to React Hook Form, which cancels it synchronously and then does the
    // rest: paint the messages, focus the first offender, and mark the form submitted. That
    // last part matters — from then on a field revalidates as it is typed into rather than
    // waiting for another blur, so a message clears while the user is still in the field
    // instead of the moment they press the mouse on the submit button, which would move the
    // button out from under the pointer and swallow the click.
    void form.handleSubmit(noop)(event)
  }

  return {
    form,
    state,
    formProps: { ref: formRef, action: formAction, onSubmit, noValidate: true },
  }
}

/** `handleSubmit` is being used for its rejection path only; there is nothing to do on the way through. */
function noop(): void {}

/**
 * Puts every `<select>` back to the value React Hook Form holds for it.
 *
 * React resets a form it submitted through an `action`, whatever that action returned. A
 * controlled `<input>` comes through that unharmed, because React keeps the `value` *attribute*
 * in step with the prop and a reset restores the attribute. It does no such thing for a
 * `<select>`: `defaultSelected` is only set on the uncontrolled `defaultValue` path, so a
 * controlled one has no option marked as its default and the reset falls back to the first in
 * the list. React's own tree still holds the real value, so the next render diffs clean and
 * never corrects the DOM — the control silently reads as something the form is not about to
 * submit.
 *
 * Assigning `value` is enough to move the selection, and it agrees with what React already
 * believes, so nothing here fights the next render.
 */
function restoreSelects(
  formElement: HTMLFormElement | null,
  valueFor: (name: string) => unknown,
): void {
  if (!formElement) return

  for (const select of formElement.querySelectorAll('select')) {
    if (!select.name) continue
    const value = valueFor(select.name)
    if (typeof value === 'string' && select.value !== value) select.value = value
  }
}

/**
 * The API names nested fields by their path — `model_config_json.temperature` — while the
 * form flattens them into one input per setting. A name the form does not recognise falls
 * back to its last segment, which is where the two conventions meet.
 */
function fieldNameFor<Values extends FieldValues>(
  reported: string,
  defaultValues: DefaultValues<Values>,
): Path<Values> {
  if (reported in defaultValues) return reported as Path<Values>
  const leaf = reported.slice(reported.lastIndexOf('.') + 1)
  return (leaf in defaultValues ? leaf : reported) as Path<Values>
}
