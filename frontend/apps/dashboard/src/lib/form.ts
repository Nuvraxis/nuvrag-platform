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

export function generationConfig(formData: FormData): GenerationConfig {
  return {
    temperature: number(formData, 'temperature', 0.2),
    max_tokens: Math.round(number(formData, 'max_tokens', 1024)),
    top_k: Math.round(number(formData, 'top_k', 5)),
    min_similarity: number(formData, 'min_similarity', 0.25),
  }
}
