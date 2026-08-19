'use client'

import {
  Alert,
  AlertDescription,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
  Input,
  NativeSelect,
} from '@rag/ui'
import Link from 'next/link'
import { useState, type ReactNode } from 'react'
import type { Control, UseFormReturn } from 'react-hook-form'

import { type Capability, fieldName, PROVIDERS, specFor } from '@/lib/ai-providers'
import type { AIConfigFormValues } from '@/lib/schemas'

import { FormField } from './form-field'

type Values = AIConfigFormValues
type Name = keyof Values & string

/**
 * One field on this form holds a boolean, which widens every other field's value type to
 * `string | boolean`. Text controls narrow it back at the point of use, the same way
 * `ColourField` does.
 */
function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export interface ProviderSectionProps {
  capability: Capability
  form: UseFormReturn<Values, unknown, unknown>
  providers: readonly string[]
  title: string
  description: ReactNode
  /** The embedding half, once the chatbot has chunks: changing it would strand every vector. */
  lock?: { chatbotId: string; dimension: number | null }
  /**
   * Whether a key is already stored *for the provider currently selected*. Switching provider
   * makes the stored one irrelevant — it authenticates somewhere else — so the field stops
   * offering to keep it and asks outright.
   */
  credentialsSet: boolean
  verified: boolean
  testButton: ReactNode
}

export function ProviderSection({
  capability,
  form,
  providers,
  title,
  description,
  lock,
  credentialsSet,
  verified,
  testButton,
}: ProviderSectionProps) {
  const control = form.control as unknown as Control<Values>
  const provider = String(form.watch(`${capability}_provider` as Name))
  const spec = specFor(capability, provider)
  const locked = Boolean(lock)

  return (
    <Card>
      <CardHeader>
        <div className="space-y-1">
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
      </CardHeader>

      <CardContent>
        <FieldGroup>
          {lock ? (
            <Alert variant="warning">
              <AlertDescription>
                This chatbot already has indexed passages
                {lock.dimension ? `, ${lock.dimension} dimensions wide` : ''}. Vectors from one
                model cannot be compared against another&rsquo;s, so the provider and model are
                fixed until its{' '}
                <Link
                  href={`/chatbots/${lock.chatbotId}/documents`}
                  className="font-medium underline underline-offset-4"
                >
                  documents are deleted
                </Link>
                .
              </AlertDescription>
            </Alert>
          ) : null}

          <FormField
            control={control}
            name={`${capability}_provider` as Name}
            label="Provider"
            description={
              capability === 'embedding'
                ? 'Anthropic is absent because it publishes no embeddings API.'
                : undefined
            }
          >
            {({ field, invalid }) => (
              <NativeSelect
                {...field}
                value={asText(field.value)}
                id={field.name}
                aria-invalid={invalid}
                disabled={locked}
              >
                {providers.map((name) => (
                  <option key={name} value={name}>
                    {PROVIDERS[name as keyof typeof PROVIDERS]?.label ?? name}
                  </option>
                ))}
              </NativeSelect>
            )}
          </FormField>

          <FormField
            control={control}
            name={`${capability}_model` as Name}
            label={spec.modelLabel}
            description={spec.modelDescription}
          >
            {({ field, invalid }) => (
              <Input
                {...field}
                value={asText(field.value)}
                id={field.name}
                spellCheck={false}
                autoComplete="off"
                placeholder={spec.modelPlaceholder}
                aria-invalid={invalid}
                disabled={locked}
              />
            )}
          </FormField>

          {spec.connection.map((entry) => (
            <FormField
              key={entry.key}
              control={control}
              name={fieldName(capability, entry.key) as Name}
              label={entry.required ? entry.label : `${entry.label} (optional)`}
              description={entry.description}
            >
              {({ field, invalid }) => (
                <Input
                  {...field}
                  value={asText(field.value)}
                  id={field.name}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder={entry.placeholder}
                  aria-invalid={invalid}
                />
              )}
            </FormField>
          ))}

          {spec.credentials.length > 0 ? (
            <CredentialFields
              capability={capability}
              control={control}
              spec={spec}
              stored={credentialsSet}
            />
          ) : (
            <Field>
              <FieldDescription>
                {spec.label} needs no credentials — reaching the server is the whole of it.
              </FieldDescription>
            </Field>
          )}

          {spec.thinking ? (
            <FormField
              control={control}
              name={`${capability}_think` as Name}
              label="Let the model think before answering"
              orientation="horizontal"
              description="Reasoning is never shown to visitors either way. Turn it off if answers come back empty — a reasoning model can spend the whole token budget thinking."
            >
              {({ field }) => (
                <input
                  type="checkbox"
                  id={field.name}
                  name={field.name}
                  ref={field.ref}
                  checked={Boolean(field.value)}
                  onBlur={field.onBlur}
                  onChange={(event) => field.onChange(event.target.checked)}
                  className="border-input accent-primary size-4 shrink-0 rounded-sm border"
                />
              )}
            </FormField>
          ) : null}
        </FieldGroup>
      </CardContent>

      <CardFooter className="flex-wrap items-center gap-3">
        {testButton}
        <span className="text-muted-foreground text-sm" role="status">
          {verified
            ? 'Ready to save.'
            : 'Test this connection before saving — the key is only proven by using it.'}
        </span>
      </CardFooter>
    </Card>
  )
}

/**
 * A stored credential is never sent back, so there is nothing to pre-fill and no dots to
 * render. The control reveals an empty field instead, the same posture as the chatbot's
 * secret key: what exists is reported, what it is is not.
 */
function CredentialFields({
  capability,
  control,
  spec,
  stored,
}: {
  capability: Capability
  control: Control<Values>
  spec: ReturnType<typeof specFor>
  stored: boolean
}) {
  const [replacing, setReplacing] = useState(false)

  if (stored && !replacing) {
    return (
      <FieldSet>
        <FieldLegend variant="label">Credentials</FieldLegend>
        <Field orientation="horizontal">
          <FieldLabel className="text-muted-foreground font-normal">
            A {spec.label} key is stored for this chatbot.
          </FieldLabel>
          <Button type="button" variant="secondary" size="sm" onClick={() => setReplacing(true)}>
            Replace
          </Button>
        </Field>
        <FieldDescription>
          Leave it alone and it stays in use. Replacing it needs the new value in full — the
          existing one cannot be read back to edit.
        </FieldDescription>
      </FieldSet>
    )
  }

  return (
    <FieldSet>
      <FieldLegend variant="label">Credentials</FieldLegend>
      <FieldGroup>
        {spec.credentials.map((entry) => (
          <FormField
            key={entry.key}
            control={control}
            name={fieldName(capability, entry.key) as Name}
            label={entry.label}
          >
            {({ field, invalid }) => (
              <Input
                {...field}
                value={asText(field.value)}
                id={field.name}
                type="password"
                // `new-password` rather than `off`: browsers ignore `off` on password fields
                // and would offer to fill this with the user's own dashboard password.
                autoComplete="new-password"
                spellCheck={false}
                placeholder={entry.placeholder}
                aria-invalid={invalid}
              />
            )}
          </FormField>
        ))}
        {stored ? (
          <FieldDescription>Leaving these empty keeps the key already stored.</FieldDescription>
        ) : null}
      </FieldGroup>
    </FieldSet>
  )
}
