import { CHAT_PROVIDERS, CHATBOT_STATUSES, EMBEDDING_PROVIDERS, USER_ROLES } from '@rag/types'
import { z } from 'zod'

import { fieldName, specFor } from './ai-providers'

/**
 * Client-side mirrors of the API's Pydantic models.
 *
 * They exist to catch a mistake before the round trip, not to replace the server's checks:
 * every Server Action still validates, and a 422 lands back on the same fields through
 * `useActionForm`. Each schema describes the *form* rather than the request body — values
 * arrive as the strings an input produces, and the actions keep parsing `FormData` exactly
 * as they did, so a submission with JavaScript disabled behaves identically.
 */

/**
 * Mirrors `settings.security.password_min_length`. That is a deployment setting rather than
 * part of the published schema, so this can drift from an instance that raised it — the
 * server's own message is what the user ends up seeing if it does.
 */
export const PASSWORD_MIN_LENGTH = 10

/** Mirrors `ChatbotCreate.allowed_origins`, which is capped at 50 entries. */
const ORIGIN_LIMIT = 50

const email = z.email('Enter a valid email address.')

const fullName = z.string().max(200, 'Keep this to 200 characters or fewer.')

const newPassword = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `Use at least ${PASSWORD_MIN_LENGTH} characters.`)
  .max(256, 'Passwords are limited to 256 characters.')

export const loginSchema = z.object({
  email,
  password: z.string().min(1, 'Enter your password.').max(256),
})

export const signupSchema = z.object({
  organization_name: z
    .string()
    .min(2, 'Give the organisation a name of at least two characters.')
    .max(200, 'Keep this to 200 characters or fewer.'),
  full_name: fullName,
  email,
  password: newPassword,
})

export const acceptInvitationSchema = z.object({
  full_name: fullName,
  password: newPassword,
})

export const inviteMemberSchema = z.object({
  email,
  role: z.enum(USER_ROLES),
})

/**
 * Mirrors `_validate_origins` in `app/schemas/chatbot.py`: scheme and host only, no wildcard.
 * The textarea holds one per line, and the action splits it — so the schema checks the text
 * the user actually typed and reports the entry that is wrong by name.
 */
function originProblem(value: string): string | null {
  const entries = value
    .split(/[\s,]+/)
    .map((entry) => entry.trim().replace(/\/+$/, ''))
    .filter(Boolean)

  if (entries.length > ORIGIN_LIMIT) {
    return `List at most ${ORIGIN_LIMIT} origins.`
  }

  for (const entry of entries) {
    if (entry === '*') {
      return 'Wildcards are not allowed — list each embedding site explicitly.'
    }

    let parsed: URL
    try {
      parsed = new URL(entry)
    } catch {
      return `${entry} is not a valid origin; expected https://example.com.`
    }

    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return `${entry} must start with http:// or https://.`
    }
    if (parsed.pathname !== '/' || parsed.search || parsed.hash) {
      return `${entry} must not include a path or query string.`
    }
  }

  return null
}

/**
 * `<input type="number">` hands back a string, and an emptied field hands back `''`. Coercing
 * that to `0` would quietly save a number the user never chose, so it is reported as missing.
 */
function numeric(label: string, min: number, max: number) {
  return z
    .union([z.number(), z.string()])
    .transform((value) => (typeof value === 'string' ? value.trim() : value))
    .refine((value) => value !== '' && Number.isFinite(Number(value)), {
      message: `${label} must be a number.`,
    })
    .transform(Number)
    .refine((value) => value >= min && value <= max, {
      message: `${label} must be between ${min} and ${max}.`,
    })
}

/** Mirrors `RETENTION_MIN_DAYS` / `RETENTION_MAX_DAYS` in `app/models/chatbot.py`. */
export const RETENTION_MIN_DAYS = 1
export const RETENTION_MAX_DAYS = 3650

/** Mirrors `USAGE_CAP_MIN` / `USAGE_CAP_MAX` in `app/models/chatbot.py`. */
export const USAGE_CAP_MIN = 1
export const USAGE_CAP_MAX = 1_000_000_000

const DAYS = { min: RETENTION_MIN_DAYS, max: RETENTION_MAX_DAYS, unit: 'days' }
const CAP_UNITS = { min: USAGE_CAP_MIN, max: USAGE_CAP_MAX, unit: 'units' }

/**
 * The fields whose *empty* value means something. Blank is "no limit" — "keep this forever"
 * for the two retention windows, "spend without a ceiling" for the two usage caps — and none
 * of them is the same as zero, which the API and the database both refuse precisely because
 * it would read as "allow nothing". `numeric` reports blank as missing, which is right for
 * every other field on this form and wrong for these four.
 *
 * One builder rather than four hand-written schemas, so they cannot drift into validating
 * differently. What they legitimately differ on is their bounds, their wording, and — for
 * memory retention alone — a non-blank starting value, which lives in `chatbotDefaults`.
 */
function blankableNumber(
  label: string,
  blankMeans: string,
  { min, max, unit }: { min: number; max: number; unit: string },
) {
  return z
    .union([z.number(), z.string()])
    .transform((value) => (typeof value === 'string' ? value.trim() : value))
    .refine((value) => value === '' || Number.isInteger(Number(value)), {
      message: `Enter a whole number of ${unit}, or leave it blank to ${blankMeans}.`,
    })
    .refine((value) => value === '' || (Number(value) >= min && Number(value) <= max), {
      message: `${label} must be between ${min} and ${max} ${unit}.`,
    })
}

const retentionDays = blankableNumber('Retention', 'keep conversations forever', DAYS)

/** Mirrors `NUVRAG_MEM_RETENTION_MIN_DAYS` / `_MAX_DAYS`, which are the same bounds. */
const memoryRetentionDays = blankableNumber('Memory retention', 'keep visitor memory forever', DAYS)

const ingestionCap = blankableNumber('The ingestion limit', 'allow unlimited uploads', CAP_UNITS)
const retrievalCap = blankableNumber('The answer limit', 'allow unlimited answers', CAP_UNITS)

/**
 * One schema for both chatbot forms. They edit the same fields and only the settings form
 * offers a status, so that member is optional rather than living in a second schema — which
 * would give the two forms different value types and stop them sharing `ChatbotFields`.
 */
export const chatbotSchema = z.object({
  name: z
    .string()
    .min(1, 'Give the chatbot a name.')
    .max(200, 'Keep the name to 200 characters or fewer.'),
  description: z.string().max(1000, 'Keep the description to 1000 characters or fewer.'),
  system_prompt: z.string().max(8000, 'Keep the system prompt to 8000 characters or fewer.'),
  allowed_origins: z.string().superRefine((value, ctx) => {
    const problem = originProblem(value)
    if (problem) ctx.addIssue({ code: 'custom', message: problem })
  }),
  temperature: numeric('Temperature', 0, 2),
  max_tokens: numeric('Max response tokens', 64, 8192),
  top_k: numeric('Passages retrieved', 1, 20),
  min_similarity: numeric('Minimum similarity', 0, 1),
  retention_days: retentionDays,
  nuvrag_mem_retention_days: memoryRetentionDays,
  monthly_ingestion_unit_cap: ingestionCap,
  monthly_retrieval_call_cap: retrievalCap,
  usage_cap_message: z.string().max(1000, 'Keep the message to 1000 characters or fewer.'),
  status: z.enum(CHATBOT_STATUSES).optional(),
})

/**
 * Mirrors `WidgetTheme`: six digits of hex, no shorthand. The widget writes these into a
 * style attribute, so the narrow pattern is the point rather than a convenience.
 */
const colour = z.string().regex(/^#[0-9a-fA-F]{6}$/, 'Use a six-digit hex colour, like #2563eb.')

/**
 * Mirrors `validate_link` in `app/schemas/chatbot.py`: absolute, http(s), with a host. Empty
 * is allowed and means no link — the widget hides a footer entry it was given nothing for.
 *
 * `new URL` rather than a pattern, for the same reason the widget parses instead of matching:
 * the parser's own reading of the scheme is what rejects `javascript:` and its obfuscations,
 * and a blocklist is a list of the ones somebody thought of.
 */
const footerLink = z
  .string()
  .max(500, 'Keep the link to 500 characters or fewer.')
  .refine(
    (value) => {
      const link = value.trim()
      if (!link) return true
      try {
        const parsed = new URL(link)
        return (parsed.protocol === 'https:' || parsed.protocol === 'http:') && !!parsed.host
      } catch {
        return false
      }
    },
    { message: 'Enter a full address, like https://example.com/privacy.' },
  )

export const widgetThemeSchema = z.object({
  accent: colour,
  accent_foreground: colour,
  surface: colour,
  surface_muted: colour,
  border: colour,
  text: colour,
  text_muted: colour,
  radius: numeric('Corner radius', 0, 28),
  scheme: z.enum(['system', 'light', 'dark']),
  position: z.enum(['right', 'left']),
  title: z.string().max(60, 'Keep the header to 60 characters or fewer.'),
  greeting: z.string().max(300, 'Keep the greeting to 300 characters or fewer.'),
  privacy_url: footerLink,
  terms_url: footerLink,
})

/**
 * Mirrors `AIConfigUpdate` — but only the parts a form can know about.
 *
 * Which connection fields are required depends on the chosen provider, so that check is a
 * `superRefine` reading the same table the inputs render from. Credentials are deliberately
 * *not* required: a blank field means "keep the key already stored", which is exactly what
 * the API does with an omitted `credentials` object. What actually stops an unusable
 * configuration being saved is the connection test, which the API performs for real.
 */
export const aiConfigSchema = z
  .object({
    chat_provider: z.enum(CHAT_PROVIDERS),
    chat_model: z
      .string()
      .min(1, 'Name the model to use.')
      .max(200, 'Keep this to 200 characters.'),
    chat_endpoint: z.string().max(500),
    chat_api_version: z.string().max(40),
    chat_region: z.string().max(40),
    chat_base_url: z.string().max(500),
    chat_api_key: z.string().max(512),
    chat_access_key_id: z.string().max(128),
    chat_secret_access_key: z.string().max(512),
    chat_think: z.boolean(),
    embedding_provider: z.enum(EMBEDDING_PROVIDERS),
    embedding_model: z
      .string()
      .min(1, 'Name the model to use.')
      .max(200, 'Keep this to 200 characters.'),
    embedding_endpoint: z.string().max(500),
    embedding_api_version: z.string().max(40),
    embedding_region: z.string().max(40),
    embedding_base_url: z.string().max(500),
    embedding_api_key: z.string().max(512),
    embedding_access_key_id: z.string().max(128),
    embedding_secret_access_key: z.string().max(512),
  })
  .superRefine((values, ctx) => {
    for (const capability of ['chat', 'embedding'] as const) {
      const provider = values[`${capability}_provider`]
      for (const field of specFor(capability, provider).connection) {
        const path = fieldName(capability, field.key)
        const value = String(values[path as keyof typeof values] ?? '').trim()

        if (field.required && !value) {
          ctx.addIssue({ code: 'custom', path: [path], message: `${field.label} is required.` })
          continue
        }
        if (value && URL_KEYS.includes(field.key) && !/^https?:\/\//i.test(value)) {
          ctx.addIssue({
            code: 'custom',
            path: [path],
            message: 'Start the address with http:// or https://.',
          })
        }
      }
    }
  })

const URL_KEYS = ['endpoint', 'base_url']

/** Mirrors `TicketReply.content`. */
export const ticketReplySchema = z.object({
  content: z
    .string()
    .min(1, 'Write a reply before sending.')
    .max(8000, 'Keep the reply to 8000 characters or fewer.'),
})

// Uploads are validated per file by `lib/uploads.ts` rather than by a schema here: the
// uploader queues several at once and needs a verdict for each, which one field-level error
// cannot carry.

export type LoginValues = z.infer<typeof loginSchema>
export type SignupValues = z.infer<typeof signupSchema>
export type AcceptInvitationValues = z.infer<typeof acceptInvitationSchema>
export type InviteMemberValues = z.infer<typeof inviteMemberSchema>
export type ChatbotValues = z.input<typeof chatbotSchema>
export type WidgetThemeValues = z.input<typeof widgetThemeSchema>
export type AIConfigFormValues = z.input<typeof aiConfigSchema>
export type TicketReplyValues = z.infer<typeof ticketReplySchema>
