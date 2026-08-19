'use client'

import { Alert, AlertDescription, Card, CardContent, Field, FieldGroup, Input } from '@rag/ui'
import Link from 'next/link'

import { loginAction } from '@/lib/actions/auth'
import { loginSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'

import { FormField } from './form-field'
import { SubmitButton } from './submit-button'

export function LoginForm({ next }: { next?: string }) {
  const { form, state, formProps } = useActionForm({
    action: loginAction,
    schema: loginSchema,
    defaultValues: { email: '', password: '' },
    announceSuccess: false,
  })

  return (
    <Card>
      <CardContent className="space-y-5">
        <form {...formProps}>
          {next ? <input type="hidden" name="next" value={next} /> : null}

          <FieldGroup>
            {state.status === 'error' && state.message ? (
              <Alert variant="destructive" role="status" className="no-js-only">
                <AlertDescription>{state.message}</AlertDescription>
              </Alert>
            ) : null}

            <FormField control={form.control} name="email" label="Work email">
              {({ field, invalid }) => (
                <Input
                  {...field}
                  id={field.name}
                  type="email"
                  autoComplete="username"
                  required
                  aria-invalid={invalid}
                />
              )}
            </FormField>

            <FormField control={form.control} name="password" label="Password">
              {({ field, invalid }) => (
                <Input
                  {...field}
                  id={field.name}
                  type="password"
                  autoComplete="current-password"
                  required
                  aria-invalid={invalid}
                />
              )}
            </FormField>

            <Field>
              <SubmitButton className="w-full" pendingLabel="Signing in…">
                Sign in
              </SubmitButton>
            </Field>
          </FieldGroup>
        </form>

        <p className="text-muted-foreground text-sm">
          No account yet?{' '}
          <Link href="/signup" className="text-primary font-medium hover:underline">
            Create an organisation
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
