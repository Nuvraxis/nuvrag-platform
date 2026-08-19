'use client'

import { Button, Spinner } from '@rag/ui'
import type { ComponentProps } from 'react'
import { useFormStatus } from 'react-dom'

export interface SubmitButtonProps extends Omit<ComponentProps<typeof Button>, 'type'> {
  pendingLabel?: string
}

/**
 * Reads the enclosing form's state, so it works for both `useActionState` forms and plain
 * `<form action={serverAction}>` without either having to thread a `pending` prop down.
 */
export function SubmitButton({ children, pendingLabel, disabled, ...props }: SubmitButtonProps) {
  const { pending } = useFormStatus()

  return (
    <Button type="submit" disabled={pending || disabled} aria-busy={pending} {...props}>
      {pending ? <Spinner /> : null}
      {pending && pendingLabel ? pendingLabel : children}
    </Button>
  )
}
