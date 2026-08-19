'use client'

import type { AIConfig } from '@rag/api-client'
import { CHAT_PROVIDERS, EMBEDDING_PROVIDERS } from '@rag/types'
import { Alert, AlertDescription, Button, Spinner } from '@rag/ui'
import { useState } from 'react'
import { useFormStatus } from 'react-dom'

import { type AIConfigTested, aiConfigAction } from '@/lib/actions/ai-config'
import { type Capability, aiConfigDefaults, specFor } from '@/lib/ai-providers'
import { type AIConfigFormValues, aiConfigSchema } from '@/lib/schemas'
import { useActionForm } from '@/lib/use-action-form'
import { useHydrated } from '@/lib/use-hydrated'

import { ProviderSection } from './provider-section'
import { SubmitButton } from './submit-button'

export interface ChatbotAIFormProps {
  chatbotId: string
  config: AIConfig | null
}

export function ChatbotAIForm({ chatbotId, config }: ChatbotAIFormProps) {
  const { form, state, formProps } = useActionForm({
    action: aiConfigAction,
    schema: aiConfigSchema,
    defaultValues: aiConfigDefaults(config),
  })

  const values = form.watch()

  /**
   * A section counts as proven when a test has succeeded against exactly the values it now
   * holds. What is already saved starts out proven: the API accepted it, and asking someone
   * to re-test a half they have not touched to save a change to the other one would be
   * ceremony rather than safety.
   */
  const [proven, setProven] = useState<Partial<Record<Capability, string>>>(() =>
    config
      ? {
          chat: signature('chat', aiConfigDefaults(config)),
          embedding: signature('embedding', aiConfigDefaults(config)),
        }
      : {},
  )

  // Recorded when the button is pressed, because the verdict that comes back says which half
  // was tested but not what it held at the time — and the fields may have moved on since.
  const [submitted, setSubmitted] = useState<{
    capability: Capability
    signature: string
  } | null>(null)

  // Adjusted while rendering rather than in an effect. `useActionState` hands back a new
  // object per submission, so identity is what marks a result as unseen; React re-runs this
  // component immediately without committing the intermediate paint, where an effect would
  // have committed one render showing the old verdict.
  const [seen, setSeen] = useState(state)
  if (seen !== state) {
    setSeen(state)
    const outcome = state.data as AIConfigTested | undefined

    if (outcome?.ok && submitted && submitted.capability === outcome.tested) {
      setProven((current) => ({ ...current, [submitted.capability]: submitted.signature }))
    } else if (state.status === 'success' && outcome === undefined) {
      // A save proves nothing new, but it does move the baseline: what is stored is now what
      // is on screen, so neither half is newly in doubt.
      setProven({
        chat: signature('chat', form.getValues()),
        embedding: signature('embedding', form.getValues()),
      })
    }
  }

  const gated = useHydrated()
  const chatProven = proven.chat === signature('chat', values)
  const embeddingProven = proven.embedding === signature('embedding', values)
  const locked = Boolean(config?.embedding_locked)

  function markSubmitted(capability: Capability) {
    setSubmitted({ capability, signature: signature(capability, form.getValues()) })
  }

  return (
    <form {...formProps} className="space-y-6">
      <input type="hidden" name="chatbot_id" value={chatbotId} />

      <ProviderSection
        capability="chat"
        form={form}
        providers={CHAT_PROVIDERS}
        title="Chat"
        description="Writes the answers, from the passages retrieved for each question."
        credentialsSet={credentialsStillApply(config, 'chat', String(values.chat_provider))}
        verified={chatProven}
        testButton={
          <IntentButton intent="test-chat" onPress={() => markSubmitted('chat')}>
            Test chat connection
          </IntentButton>
        }
      />

      <ProviderSection
        capability="embedding"
        form={form}
        providers={EMBEDDING_PROVIDERS}
        title="Embeddings"
        description="Turns documents and questions into vectors. Both sides must come from the same model for a comparison between them to mean anything."
        lock={locked ? { chatbotId, dimension: config?.embedding_dimension ?? null } : undefined}
        credentialsSet={credentialsStillApply(
          config,
          'embedding',
          String(values.embedding_provider),
        )}
        verified={embeddingProven}
        testButton={
          <IntentButton intent="test-embedding" onPress={() => markSubmitted('embedding')}>
            Test embedding connection
          </IntentButton>
        }
      />

      {/* Every outcome here — a save, and either connection test — arrives as a toast, the
          same as the rest of the dashboard. This carries the same words for a visitor with no
          scripts, who gets no toast and no test button either. */}
      {state.message ? (
        <Alert
          variant={state.status === 'error' ? 'destructive' : 'default'}
          role="status"
          className="no-js-only"
        >
          <AlertDescription>{state.message}</AlertDescription>
        </Alert>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        {/* The gate is an affordance, not the rule. `disabled` renders into the HTML, so
            applying it before hydration would hand a visitor with no JavaScript a button that
            can never be pressed — and there is no test button for them to satisfy it with
            either. Without scripts the form simply posts, and the API stays the authority on
            whether the configuration works. */}
        <SubmitButton
          name="intent"
          value="save"
          pendingLabel="Saving…"
          disabled={gated && (!chatProven || !embeddingProven)}
        >
          Save providers
        </SubmitButton>
        {gated && !(chatProven && embeddingProven) ? (
          <p className="text-muted-foreground text-sm">
            Both connections need a successful test before this can be saved.
          </p>
        ) : null}
      </div>
    </form>
  )
}

/**
 * One button that submits the shared form under its own intent.
 *
 * `useFormStatus` reports the whole form as pending, so every button would otherwise claim to
 * be the one working. It also hands back the `FormData` being submitted, which already
 * contains the submitter's own name and value — so which button is busy is a fact about the
 * submission rather than something this component has to remember.
 */
function IntentButton({
  intent,
  onPress,
  children,
}: {
  intent: string
  onPress: () => void
  children: React.ReactNode
}) {
  const { pending, data } = useFormStatus()
  const active = pending && data?.get('intent') === intent

  return (
    <Button
      type="submit"
      name="intent"
      value={intent}
      variant="secondary"
      disabled={pending}
      aria-busy={active}
      onClick={onPress}
    >
      {active ? <Spinner /> : null}
      {active ? 'Testing…' : children}
    </Button>
  )
}

/** Everything a test would exercise, so any edit to it invalidates the last result. */
function signature(capability: Capability, values: AIConfigFormValues): string {
  const provider = String(values[`${capability}_provider` as keyof AIConfigFormValues])
  const spec = specFor(capability, provider)
  const parts = [
    provider,
    String(values[`${capability}_model` as keyof AIConfigFormValues] ?? ''),
    ...spec.connection.map((field) =>
      String(values[`${capability}_${field.key}` as keyof AIConfigFormValues] ?? ''),
    ),
    ...spec.credentials.map((field) =>
      String(values[`${capability}_${field.key}` as keyof AIConfigFormValues] ?? ''),
    ),
  ]
  if (spec.thinking) parts.push(String(values[`${capability}_think` as keyof AIConfigFormValues]))
  return JSON.stringify(parts)
}

/** A key stored for Azure authenticates nowhere near Bedrock. */
function credentialsStillApply(
  config: AIConfig | null,
  capability: Capability,
  provider: string,
): boolean {
  const half = capability === 'chat' ? config?.chat : config?.embedding
  return Boolean(half?.credentials_set) && half?.provider === provider
}
