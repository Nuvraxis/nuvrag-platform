'use server'

import type {
  AIConfigUpdate,
  ChatProviderName,
  ChatTarget,
  EmbeddingProviderName,
  EmbeddingTarget,
} from '@rag/api-client'
import { CHAT_PROVIDERS, EMBEDDING_PROVIDERS } from '@rag/types'
import { revalidatePath } from 'next/cache'

import { type ActionState, failed, fromError, succeeded } from '@/lib/action-state'
import {
  type Capability,
  CONNECTION_KEYS,
  CREDENTIAL_KEYS,
  fieldName,
  specFor,
} from '@/lib/ai-providers'
import { authenticatedApi } from '@/lib/api'
import { text } from '@/lib/form'

/** What the client needs to know about a test that has just run. */
export interface AIConfigTested {
  tested: Capability
  ok: boolean
  embeddingDimension?: number | null
}

/**
 * Save and test share one action because they share one set of fields.
 *
 * They are separate submit buttons carrying `intent`, which is what lets a browser with no
 * JavaScript use either: the submitter's name and value are part of a native submission, so
 * the same form serves both without duplicating every input into a second one.
 */
export async function aiConfigAction(
  _previous: ActionState<AIConfigTested>,
  formData: FormData,
): Promise<ActionState<AIConfigTested>> {
  const chatbotId = text(formData, 'chatbot_id')
  if (!chatbotId) {
    return failed('Missing chatbot reference.')
  }

  const intent = text(formData, 'intent')
  if (intent === 'test-chat' || intent === 'test-embedding') {
    return testConnection(chatbotId, formData, intent === 'test-chat' ? 'chat' : 'embedding')
  }
  return saveConfig(chatbotId, formData)
}

async function saveConfig(
  chatbotId: string,
  formData: FormData,
): Promise<ActionState<AIConfigTested>> {
  const chat = chatTarget(formData)
  const embedding = embeddingTarget(formData)
  const missing = missingConnection('chat', chat) ?? missingConnection('embedding', embedding)
  if (missing) return missing

  const body: AIConfigUpdate = { chat, embedding }

  const api = await authenticatedApi()
  try {
    await api.updateAIConfig(chatbotId, body)
  } catch (error) {
    return fromError(error)
  }

  revalidatePath(`/chatbots/${chatbotId}`, 'layout')
  return succeeded('AI providers saved.')
}

async function testConnection(
  chatbotId: string,
  formData: FormData,
  capability: Capability,
): Promise<ActionState<AIConfigTested>> {
  const target = capability === 'chat' ? chatTarget(formData) : embeddingTarget(formData)
  const missing = missingConnection(capability, target)
  if (missing) return { ...missing, data: { tested: capability, ok: false } }

  const api = await authenticatedApi()
  try {
    const result = await api.testAIConfig(
      chatbotId,
      capability === 'chat'
        ? { chat: target as ChatTarget }
        : { embedding: target as EmbeddingTarget },
    )

    if (!result.ok) {
      // Carries `tested` even in failure, so the form knows which half is still unproven. The
      // API has already reduced the provider's own words to one of a fixed set of phrases.
      return {
        status: 'error',
        message: `${halfName(capability)}: ${uncapitalise(result.error ?? 'The connection test failed.')}`,
        data: { tested: capability, ok: false },
      }
    }

    return succeeded(
      capability === 'chat'
        ? 'Chat: the model answered.'
        : dimensionMessage(result.embedding_dimension),
      { tested: capability, ok: true, embeddingDimension: result.embedding_dimension },
    )
  } catch (error) {
    return fromError(error)
  }
}

function dimensionMessage(dimension: number | null | undefined): string {
  return dimension
    ? `Embeddings: the model answered with ${dimension}-dimension vectors.`
    : 'Embeddings: the model answered.'
}

function chatTarget(formData: FormData): ChatTarget {
  const provider = chatProvider(formData)
  return {
    provider,
    model: text(formData, 'chat_model'),
    connection: {
      ...connection('chat', provider, formData),
      // An unchecked checkbox submits nothing at all, so absence is the "off" that a
      // present value cannot express.
      think: formData.get(fieldName('chat', 'think')) !== null,
    },
    credentials: credentials('chat', provider, formData),
  }
}

function embeddingTarget(formData: FormData): EmbeddingTarget {
  const provider = embeddingProvider(formData)
  return {
    provider,
    model: text(formData, 'embedding_model'),
    connection: connection('embedding', provider, formData),
    credentials: credentials('embedding', provider, formData),
  }
}

/** Only the keys this provider uses, so a stale value from a previous choice is not stored. */
function connection(
  capability: Capability,
  provider: string,
  formData: FormData,
): Record<string, string> {
  const wanted = new Set(specFor(capability, provider).connection.map((field) => field.key))
  const result: Record<string, string> = {}
  for (const key of CONNECTION_KEYS) {
    const value = text(formData, fieldName(capability, key))
    if (wanted.has(key) && value) result[key] = value
  }
  return result
}

/**
 * `undefined` keeps whatever is stored; an object replaces it.
 *
 * A revealed-but-empty field therefore changes nothing, which is the right reading of a user
 * who opened the control and thought better of it. Clearing a credential is deliberately not
 * something this form offers — switching provider is what makes one irrelevant.
 */
function credentials(
  capability: Capability,
  provider: string,
  formData: FormData,
): Record<string, string> | undefined {
  const wanted = specFor(capability, provider).credentials.map((field) => field.key)
  const supplied: Record<string, string> = {}
  for (const key of CREDENTIAL_KEYS) {
    const value = text(formData, fieldName(capability, key))
    if (wanted.includes(key) && value) supplied[key] = value
  }
  return Object.keys(supplied).length > 0 ? supplied : undefined
}

/**
 * The same requirement the API enforces, checked here so a browser running no JavaScript is
 * told which field is missing instead of being handed a generic 422.
 */
function missingConnection(
  capability: Capability,
  target: ChatTarget | EmbeddingTarget,
): ActionState<AIConfigTested> | null {
  if (!target.model) {
    return failed(`${halfName(capability)}: name the model to use.`, {
      [fieldName(capability, 'model')]: 'Required.',
    })
  }

  const stored = (target.connection ?? {}) as Record<string, string>
  for (const field of specFor(capability, target.provider).connection) {
    if (field.required && !stored[field.key]) {
      return failed(`${halfName(capability)}: ${field.label.toLowerCase()} is required.`, {
        [fieldName(capability, field.key)]: `${field.label} is required.`,
      })
    }
  }
  return null
}

/**
 * Which of the two sections a message is about.
 *
 * The page holds a chat half and an embedding half, and every outcome is announced as a toast
 * rather than beside the section it came from — so the message has to say which one it means.
 * The field-level errors still land on the field itself and need no such help.
 */
function halfName(capability: Capability): string {
  return capability === 'chat' ? 'Chat' : 'Embeddings'
}

/** The API's phrases are whole sentences; behind "Embeddings:" they read as clauses. */
function uncapitalise(sentence: string): string {
  return sentence.charAt(0).toLowerCase() + sentence.slice(1)
}

function chatProvider(formData: FormData): ChatProviderName {
  const value = text(formData, 'chat_provider')
  return (CHAT_PROVIDERS as readonly string[]).includes(value)
    ? (value as ChatProviderName)
    : 'ollama'
}

function embeddingProvider(formData: FormData): EmbeddingProviderName {
  const value = text(formData, 'embedding_provider')
  return (EMBEDDING_PROVIDERS as readonly string[]).includes(value)
    ? (value as EmbeddingProviderName)
    : 'ollama'
}
