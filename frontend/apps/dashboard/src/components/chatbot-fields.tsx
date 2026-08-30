'use client'

import type { Chatbot, GenerationConfig } from '@rag/api-client'
import { FieldGroup, FieldLegend, FieldSet, Input, Textarea } from '@rag/ui'
import { useWatch, type Control } from 'react-hook-form'

import { NUVRAG_MEM_RETENTION_DEFAULT_DAYS } from '@/lib/form'
import {
  RETENTION_MAX_DAYS,
  RETENTION_MIN_DAYS,
  USAGE_CAP_MAX,
  USAGE_CAP_MIN,
  type ChatbotValues,
} from '@/lib/schemas'

import { FormField } from './form-field'

const DEFAULT_GENERATION: Required<GenerationConfig> = {
  temperature: 0.2,
  max_tokens: 1024,
  top_k: 5,
  min_similarity: 0.25,
}

/**
 * What the form starts with, for a chatbot being edited or one that does not exist yet.
 *
 * Every member is present and never `undefined`: the inputs are controlled by React Hook
 * Form, and a field that begins undefined would switch from uncontrolled to controlled on
 * the first keystroke.
 */
export function chatbotDefaults(chatbot?: Chatbot): ChatbotValues {
  const generation = { ...DEFAULT_GENERATION, ...(chatbot?.model_config_json as GenerationConfig) }

  return {
    name: chatbot?.name ?? '',
    description: chatbot?.description ?? '',
    system_prompt: chatbot?.system_prompt ?? '',
    allowed_origins: chatbot?.allowed_origins.join('\n') ?? '',
    temperature: generation.temperature,
    max_tokens: generation.max_tokens,
    top_k: generation.top_k,
    min_similarity: generation.min_similarity,
    // Empty string rather than 0 or undefined: blank is how "keep conversations forever" is
    // spelled in this form, and it is what a chatbot with no retention set comes back as.
    retention_days: chatbot?.retention_days == null ? '' : String(chatbot.retention_days),
    // Blank means the same thing next door, but the *starting* value does not: a chatbot
    // being created starts at 30 days of memory rather than at forever. An existing chatbot
    // whose value is genuinely null has been set to keep forever on purpose, and must come
    // back blank rather than being quietly reset to the default.
    nuvrag_mem_retention_days: chatbot
      ? chatbot.nuvrag_mem_retention_days == null
        ? ''
        : String(chatbot.nuvrag_mem_retention_days)
      : String(NUVRAG_MEM_RETENTION_DEFAULT_DAYS),
    // Both caps start blank, which is unlimited. Unlike memory retention there is no
    // non-blank starting value to distinguish an absent field from a cleared one.
    monthly_ingestion_unit_cap:
      chatbot?.monthly_ingestion_unit_cap == null ? '' : String(chatbot.monthly_ingestion_unit_cap),
    monthly_retrieval_call_cap:
      chatbot?.monthly_retrieval_call_cap == null ? '' : String(chatbot.monthly_retrieval_call_cap),
    usage_cap_message: chatbot?.usage_cap_message ?? '',
    status: chatbot?.status,
  }
}

/**
 * Reads the cap from the form rather than from the saved chatbot, so the ratio reflects the
 * limit currently on screen. Everything else on this form is unsaved until saved too.
 */
function UsageLine({
  control,
  name,
  label,
  used,
}: {
  control: Control<ChatbotValues>
  name: 'monthly_ingestion_unit_cap' | 'monthly_retrieval_call_cap'
  label: string
  used: number
}) {
  const raw = String(useWatch({ control, name }) ?? '').trim()
  const cap = raw && Number.isFinite(Number(raw)) ? Number(raw) : null

  return (
    <div className="flex items-baseline justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground tabular-nums">
        {used.toLocaleString()} / {cap === null ? 'unlimited' : cap.toLocaleString()}
      </span>
    </div>
  )
}

/**
 * The editable surface of a chatbot, shared by the create and settings forms so the two can
 * never drift apart.
 */
export function ChatbotFields({
  control,
  usage,
}: {
  control: Control<ChatbotValues>
  /** This month's totals, which only the settings form has — the create form has no chatbot
      to have spent anything yet. */
  usage?: Chatbot['usage']
}) {
  return (
    <>
      <FormField
        control={control}
        name="name"
        label="Name"
        description="The URL slug is generated from this and kept unique automatically."
      >
        {({ field, invalid }) => (
          <Input {...field} id={field.name} required maxLength={200} aria-invalid={invalid} />
        )}
      </FormField>

      <FormField control={control} name="description" label="Description">
        {({ field, invalid }) => (
          <Input {...field} id={field.name} maxLength={1000} aria-invalid={invalid} />
        )}
      </FormField>

      <FormField
        control={control}
        name="system_prompt"
        label="System prompt"
        description="Tone and scope instructions. Retrieved passages are added underneath at query time."
      >
        {({ field, invalid }) => (
          <Textarea
            {...field}
            id={field.name}
            rows={5}
            maxLength={8000}
            aria-invalid={invalid}
            placeholder="You are the support assistant for Acme. Answer only from the provided context."
          />
        )}
      </FormField>

      <FormField
        control={control}
        name="allowed_origins"
        label="Allowed origins"
        description="One per line, scheme and host only — https://acme.com. Wildcards are rejected. List the sites the widget is embedded on; the API checks each request against them."
      >
        {({ field, invalid }) => (
          <Textarea
            {...field}
            id={field.name}
            rows={3}
            spellCheck={false}
            className="font-mono text-xs"
            aria-invalid={invalid}
            placeholder="https://acme.com"
          />
        )}
      </FormField>

      <FormField
        control={control}
        name="retention_days"
        label="Delete conversations after"
        description="Days, counted from a conversation's last message. Leave blank to keep them indefinitely, which is the default. A conversation with an unresolved ticket is kept until the ticket is closed."
      >
        {({ field, invalid }) => (
          <Input
            {...field}
            id={field.name}
            type="number"
            inputMode="numeric"
            min={RETENTION_MIN_DAYS}
            max={RETENTION_MAX_DAYS}
            step={1}
            placeholder="Keep forever"
            aria-invalid={invalid}
          />
        )}
      </FormField>

      <FormField
        control={control}
        name="nuvrag_mem_retention_days"
        label="Delete visitor memory after"
        description="Days, counted from the last time a note was used. Unlike conversations, this starts at 30 days rather than at forever — a note is a standing summary of a person across visits, not a record of one exchange. Leave blank to keep memory indefinitely."
      >
        {({ field, invalid }) => (
          <Input
            {...field}
            id={field.name}
            type="number"
            inputMode="numeric"
            min={RETENTION_MIN_DAYS}
            max={RETENTION_MAX_DAYS}
            step={1}
            placeholder="Keep forever"
            aria-invalid={invalid}
          />
        )}
      </FormField>

      <FieldSet className="border-border rounded-xl border p-4">
        <FieldLegend variant="label" className="px-1">
          Usage limits
        </FieldLegend>
        <FieldGroup>
          <p className="text-muted-foreground text-sm">
            Ceilings on what this chatbot may spend with your AI provider in a UTC calendar month.
            Both start unlimited. They are separate from rate limiting, which shapes requests per
            second rather than cost over a month.
          </p>

          {usage ? (
            <div className="border-border bg-muted space-y-1 rounded-md border px-3 py-2">
              <p className="text-muted-foreground text-xs">
                Used this month, since {usage.period_start}
              </p>
              <UsageLine
                control={control}
                name="monthly_ingestion_unit_cap"
                label="Ingestion units"
                used={usage.ingestion_units_used}
              />
              <UsageLine
                control={control}
                name="monthly_retrieval_call_cap"
                label="Answers"
                used={usage.retrieval_calls_used}
              />
            </div>
          ) : null}

          <FormField
            control={control}
            name="monthly_ingestion_unit_cap"
            label="Ingestion units per month"
            description="One unit is 4,000 bytes of uploaded document, rounded up — so a 40 KB file costs 10. Uploads past the limit are refused until the month turns over. Leave blank for no limit."
          >
            {({ field, invalid }) => (
              <Input
                {...field}
                id={field.name}
                type="number"
                inputMode="numeric"
                min={USAGE_CAP_MIN}
                max={USAGE_CAP_MAX}
                step={1}
                placeholder="Unlimited"
                aria-invalid={invalid}
              />
            )}
          </FormField>

          <FormField
            control={control}
            name="monthly_retrieval_call_cap"
            label="Answers per month"
            description="One per answered chat turn. Past the limit the widget still replies, with the message below, and no provider call is made. Leave blank for no limit."
          >
            {({ field, invalid }) => (
              <Input
                {...field}
                id={field.name}
                type="number"
                inputMode="numeric"
                min={USAGE_CAP_MIN}
                max={USAGE_CAP_MAX}
                step={1}
                placeholder="Unlimited"
                aria-invalid={invalid}
              />
            )}
          </FormField>

          <FormField
            control={control}
            name="usage_cap_message"
            label="What visitors see once the answer limit is reached"
            description="Says nothing about limits or billing by default — a visitor can only act on the part that concerns them."
          >
            {({ field, invalid }) => (
              <Textarea
                {...field}
                id={field.name}
                rows={3}
                maxLength={1000}
                aria-invalid={invalid}
              />
            )}
          </FormField>
        </FieldGroup>
      </FieldSet>

      <FieldSet className="border-border rounded-xl border p-4">
        <FieldLegend variant="label" className="px-1">
          Retrieval and generation
        </FieldLegend>
        <FieldGroup className="grid gap-4 sm:grid-cols-2">
          <FormField
            control={control}
            name="temperature"
            label="Temperature"
            description="0 is deterministic."
          >
            {({ field, invalid }) => (
              <Input
                {...field}
                id={field.name}
                type="number"
                min={0}
                max={2}
                step={0.05}
                aria-invalid={invalid}
              />
            )}
          </FormField>

          <FormField control={control} name="max_tokens" label="Max response tokens">
            {({ field, invalid }) => (
              <Input
                {...field}
                id={field.name}
                type="number"
                min={64}
                max={8192}
                step={64}
                aria-invalid={invalid}
              />
            )}
          </FormField>

          <FormField
            control={control}
            name="top_k"
            label="Passages retrieved"
            description="How many chunks are pulled per question."
          >
            {({ field, invalid }) => (
              <Input
                {...field}
                id={field.name}
                type="number"
                min={1}
                max={20}
                aria-invalid={invalid}
              />
            )}
          </FormField>

          <FormField
            control={control}
            name="min_similarity"
            label="Minimum similarity"
            description="Below this a passage is discarded, and with nothing left the bot declines."
          >
            {({ field, invalid }) => (
              <Input
                {...field}
                id={field.name}
                type="number"
                min={0}
                max={1}
                step={0.05}
                aria-invalid={invalid}
              />
            )}
          </FormField>
        </FieldGroup>
      </FieldSet>
    </>
  )
}
