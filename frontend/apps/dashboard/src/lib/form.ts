import type { ChatbotStatus, GenerationConfig } from '@rag/api-client'
import { CHATBOT_STATUSES } from '@rag/types'

export function text(formData: FormData, name: string): string {
  const value = formData.get(name)
  return typeof value === 'string' ? value.trim() : ''
}

export function optionalText(formData: FormData, name: string): string | null {
  return text(formData, name) || null
}

export function number(formData: FormData, name: string, fallback: number): number {
  const parsed = Number(formData.get(name))
  return Number.isFinite(parsed) ? parsed : fallback
}

/** The textarea accepts one origin per line; commas and stray blank lines are tolerated. */
export function originList(formData: FormData, name: string): string[] {
  return text(formData, name)
    .split(/[\s,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
}

export function chatbotStatus(formData: FormData, name: string): ChatbotStatus | undefined {
  const value = text(formData, name)
  return (CHATBOT_STATUSES as readonly string[]).includes(value)
    ? (value as ChatbotStatus)
    : undefined
}

/**
 * Blank means "keep conversations forever", which is a value rather than a missing one — so
 * this returns `null` rather than `undefined`. The API treats a null `retention_days` as the
 * one field where null is an instruction instead of an omission, which is what makes the
 * setting reversible.
 */
export function retentionDays(formData: FormData): number | null {
  const raw = text(formData, 'retention_days')
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? Math.round(parsed) : null
}

/** A chatbot starts at 30 days of visitor memory rather than at "forever". */
export const NUVRAG_MEM_RETENTION_DEFAULT_DAYS = 30

/**
 * The same blank-means-forever spelling as `retentionDays`, with one extra distinction it
 * does not need. Conversation retention defaults to "forever", so a field that is absent and
 * a field that is blank mean the same thing. Memory defaults to 30, so they do not: absent is
 * a form that never asked, and must fall back to the default, while present-and-blank is a
 * tenant deliberately choosing to keep memory forever. `FormData.has` is what tells them
 * apart — reading the value alone cannot.
 */
export function nuvragMemRetentionDays(formData: FormData): number | null {
  if (!formData.has('nuvrag_mem_retention_days')) {
    return NUVRAG_MEM_RETENTION_DEFAULT_DAYS
  }
  const raw = text(formData, 'nuvrag_mem_retention_days')
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? Math.round(parsed) : null
}

/**
 * Blank means "go by whatever was calibrated for this chatbot's embedding model", which is a
 * value rather than a missing one — the same spelling as `retentionDays`, and the API
 * reinstates a null override for the same reason. Not rounded, unlike every other blankable
 * field here: this one is a cosine similarity, not a count of anything.
 */
export function similarityOverride(formData: FormData): number | null {
  const raw = text(formData, 'nuvrag_mem_similarity_override')
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : null
}

export function generationConfig(formData: FormData): GenerationConfig {
  return {
    temperature: number(formData, 'temperature', 0.2),
    max_tokens: Math.round(number(formData, 'max_tokens', 1024)),
    top_k: Math.round(number(formData, 'top_k', 5)),
    min_similarity: number(formData, 'min_similarity', 0.25),
  }
}

/**
 * Blank means "no ceiling", which is a value rather than a missing one — the same spelling as
 * `retentionDays`, and the API reinstates a null cap for the same reason it reinstates a null
 * retention. Both caps start unset, so absent and blank do mean the same thing here.
 */
export function usageCap(formData: FormData, name: string): number | null {
  const raw = text(formData, name)
  if (!raw) return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? Math.round(parsed) : null
}
