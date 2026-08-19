'use client'

import type { InvitationPreview } from '@rag/api-client'
import { Alert, AlertDescription, Card, CardContent, Field, FieldGroup, Input } from '@rag/ui'

import { acceptInvitationAction } from '@/lib/actions/auth'
import { PASSWORD_MIN_LENGTH, acceptInvitationSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'

import { FormField } from './form-field'
import { SubmitButton } from './submit-button'

export interface AcceptInvitationFormProps {
  token: string
  preview: InvitationPreview
}

export function AcceptInvitationForm({ token, preview }: AcceptInvitationFormProps) {
  const { form, state, formProps } = useActionForm({
    action: acceptInvitationAction,
    schema: acceptInvitationSchema,
    defaultValues: { full_name: '', password: '' },
    announceSuccess: false,
  })

  return (
    <Card>
      <CardContent className="space-y-5">
        <div className="space-y-1">
          <h2 className="text-foreground font-medium">
            Join {preview.organization_name} as {preview.role}
          </h2>
          <p className="text-muted-foreground text-sm">
            Setting a password finishes the account for <strong>{preview.email}</strong>. The
            address is fixed by the invitation and cannot be changed here.
          </p>
        </div>

        <form {...formProps}>
          <input type="hidden" name="token" value={token} />

          <FieldGroup>
            {state.status === 'error' && state.message ? (
              <Alert variant="destructive" role="status" className="no-js-only">
                <AlertDescription>{state.message}</AlertDescription>
              </Alert>
            ) : null}

            <FormField control={form.control} name="full_name" label="Your name">
              {({ field, invalid }) => (
                <Input {...field} id={field.name} autoComplete="name" aria-invalid={invalid} />
              )}
            </FormField>

            <FormField
              control={form.control}
              name="password"
              label="Choose a password"
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
              <SubmitButton className="w-full" pendingLabel="Joining…">
                Join {preview.organization_name}
              </SubmitButton>
            </Field>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}
