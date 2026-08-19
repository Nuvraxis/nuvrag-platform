import 'server-only'

import type { AIConfig } from '@rag/api-client'
import { isApiError } from '@rag/api-client'

import { authenticatedApi } from './api'

/**
 * The chatbot's provider configuration, or null when it has none yet.
 *
 * "Not configured" is a 404 from the API and an ordinary state here — it is where every
 * chatbot starts. `fetchApi` would turn it into the not-found page, which is right for a
 * chatbot id that does not exist and wrong for a chatbot that simply has not been set up.
 * The ownership check has already happened by then: a chatbot belonging to someone else
 * never reaches this call with a readable id.
 */
export async function loadAIConfig(chatbotId: string): Promise<AIConfig | null> {
  const api = await authenticatedApi()
  try {
    return await api.getAIConfig(chatbotId)
  } catch (error) {
    if (isApiError(error) && error.isNotFound) return null
    throw error
  }
}

/** Whether both halves are complete enough for uploads and answers to work. */
export function isAIConfigReady(config: AIConfig | null): boolean {
  return Boolean(config?.chat.ready && config.embedding.ready)
}
