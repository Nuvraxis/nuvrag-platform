'use client'

import { Alert, AlertDescription, Card, CardContent, Field, FieldGroup, Input } from '@rag/ui'
import Link from 'next/link'

import { signupAction } from '@/lib/actions/auth'
import { PASSWORD_MIN_LENGTH, signupSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'

import { FormField } from './form-field'
import { SubmitButton } from './submit-button'

export function SignupForm() {
  const { form, state, formProps } = useActionForm({
    action: signupAction,
    schema: signupSchema,
    defaultValues: { organization_name: '', full_name: '', email: '', password: '' },
    announceSuccess: false,
  })

  return (
    <Card>
      <CardContent className="space-y-5">
        <form {...formProps}>
          <FieldGroup>
            {state.status === 'error' && state.message ? (
              <Alert variant="destructive" role="status" className="no-js-only">
                <AlertDescription>{state.message}</AlertDescription>
              </Alert>
            ) : null}

            <FormField
              control={form.control}
              name="organization_name"
              label="Organisation name"
              description="Everything you create lives inside this organisation."
            >
              {({ field, invalid }) => (
                <Input {...field} id={field.name} required aria-invalid={invalid} />
              )}
            </FormField>

            <FormField control={form.control} name="full_name" label="Your name">
              {({ field, invalid }) => (
                <Input {...field} id={field.name} autoComplete="name" aria-invalid={invalid} />
              )}
            </FormField>

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

            <FormField
              control={form.control}
              name="password"
              label="Password"
              description={`At least ${PASSWORD_MIN_LENGTH} characters.`}
            >
              {({ field, invalid }) => (
                <Input
                  {...field}
                  id={field.name}
                  type="password"
                  autoComplete="new-password"
                  required
                  aria-invalid={invalid}
                />
              )}
            </FormField>

            <Field>
              <SubmitButton className="w-full" pendingLabel="Creating…">
                Create organisation
              </SubmitButton>
            </Field>
          </FieldGroup>
        </form>

        <p className="text-muted-foreground text-sm">
          Already have an account?{' '}
          <Link href="/login" className="text-primary font-medium hover:underline">
            Sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  )
}
