'use client'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@rag/ui'
import { type MouseEvent, useRef, useState } from 'react'

import { SubmitButton, type SubmitButtonProps } from './submit-button'

export interface ConfirmSubmitProps extends Omit<SubmitButtonProps, 'onClick'> {
  /** The question, as a question. */
  confirmTitle: string
  /** What the person is agreeing to. Required: the dialog is described by it. */
  confirmDescription: string
  /** Wording for the button that goes through with it; defaults to the trigger's own label. */
  confirmLabel?: string
}

/**
 * A submit button that asks first, in an alert dialog rather than a `window.confirm` box.
 *
 * The button stays a real submit button and the dialog is opened by cancelling its click.
 * That ordering is the whole trick: with no JavaScript the handler never runs, the click
 * submits the form as it always did, and nothing is lost but the question — which was only
 * ever a courtesy, since the API is what actually decides whether the deletion is allowed.
 *
 * Going ahead calls `requestSubmit` on the button's own form, so the enclosing `ActionForm`
 * runs exactly as it would have, `useFormStatus` reports pending on this button, and the
 * result is announced the same way as every other mutation.
 */
export function ConfirmSubmit({
  confirmTitle,
  confirmDescription,
  confirmLabel,
  children,
  variant,
  ...props
}: ConfirmSubmitProps) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement | null>(null)

  function ask(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    trigger.current = event.currentTarget
    setOpen(true)
  }

  function goAhead() {
    const button = trigger.current
    // Passing the button as the submitter keeps the submission indistinguishable from the
    // one the click would have made on its own.
    button?.form?.requestSubmit(button)
  }

  return (
    <>
      <SubmitButton variant={variant} {...props} onClick={ask}>
        {children}
      </SubmitButton>

      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmTitle}</AlertDialogTitle>
            <AlertDialogDescription>{confirmDescription}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant={variant} onClick={goAhead}>
              {confirmLabel ?? children}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
