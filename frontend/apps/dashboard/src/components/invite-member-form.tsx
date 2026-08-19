'use client'

import type { UserRole } from '@rag/api-client'
import {
  Alert,
  AlertDescription,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Field,
  FieldGroup,
  Input,
  NativeSelect,
} from '@rag/ui'

import { inviteMemberAction } from '@/lib/actions/team'
import { inviteMemberSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'

import { CopyButton } from './copy-button'
import { FormField } from './form-field'
import { SubmitButton } from './submit-button'

const ROLE_HINT: Record<UserRole, string> = {
  member: 'Can read everything and upload documents.',
  admin: 'Can also create chatbots and invite people.',
  owner: 'Full control, including billing and removing other owners.',
}

export function InviteMemberForm({ assignableRoles }: { assignableRoles: readonly UserRole[] }) {
  // The select is controlled, so its default has to be an option that is actually offered —
  // otherwise it would render blank and submit a role the form never showed.
  const defaultRole = assignableRoles.includes('member')
    ? 'member'
    : (assignableRoles[0] ?? 'member')

  const { form, state, formProps } = useActionForm({
    action: inviteMemberAction,
    schema: inviteMemberSchema,
    defaultValues: { email: '', role: defaultRole },
    resetOnSuccess: true,
  })

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>Invite someone</CardTitle>
          <CardDescription>
            There is no mail transport configured, so the link below is yours to send.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {state.status === 'error' && state.message ? (
          <Alert variant="destructive" role="status" className="no-js-only">
            <AlertDescription>{state.message}</AlertDescription>
          </Alert>
        ) : null}

        {state.status === 'success' && state.data ? (
          <Alert variant="success" className="space-y-3">
            <AlertDescription>
              <p className="font-medium">
                Send this link to {state.data.email} — it is shown once and expires in seven days.
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <code className="bg-card text-foreground min-w-0 flex-1 overflow-x-auto rounded-md px-3 py-2 font-mono text-xs">
                  {state.data.acceptUrl}
                </code>
                <CopyButton value={state.data.acceptUrl} label="Copy link" />
              </div>
            </AlertDescription>
          </Alert>
        ) : null}

        <form {...formProps}>
          <FieldGroup className="gap-4">
            {/* A grid rather than a wrapping flex row: the two fields keep their own column,
                so a message under one of them no longer drags the other out of line. */}
            <div className="grid items-start gap-4 sm:grid-cols-[minmax(14rem,1fr)_11rem]">
              <FormField control={form.control} name="email" label="Email address">
                {({ field, invalid }) => (
                  <Input
                    {...field}
                    id={field.name}
                    type="email"
                    autoComplete="off"
                    required
                    aria-invalid={invalid}
                  />
                )}
              </FormField>

              <FormField control={form.control} name="role" label="Role">
                {({ field, invalid }) => (
                  <NativeSelect {...field} id={field.name} aria-invalid={invalid}>
                    {assignableRoles.map((value) => (
                      <option key={value} value={value} title={ROLE_HINT[value]}>
                        {value}
                      </option>
                    ))}
                  </NativeSelect>
                )}
              </FormField>
            </div>

            <Field orientation="horizontal">
              <SubmitButton pendingLabel="Creating…">Create invitation</SubmitButton>
            </Field>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}
