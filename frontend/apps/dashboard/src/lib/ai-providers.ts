import type {
  AIConfig,
  ChatProviderName,
  EmbeddingProviderName,
  ProviderRead,
} from '@rag/api-client'

/**
 * What each provider asks for, mirroring `app/services/ai/registry.py`.
 *
 * The form renders from this table rather than from a switch per section, so adding a
 * provider is one entry here plus one in the backend's registry — and the two are checked
 * against each other by the API, which refuses a payload missing a connection field whatever
 * this file believes.
 */

export type Capability = 'chat' | 'embedding'

/** Non-secret. Stored in the clear and returned by `GET`. */
export type ConnectionKey = 'endpoint' | 'api_version' | 'region' | 'base_url'
/** Write-only. Never returned, never pre-filled. */
export type CredentialKey = 'api_key' | 'access_key_id' | 'secret_access_key'

export interface ConnectionField {
  key: ConnectionKey
  label: string
  placeholder: string
  description?: string
  required: boolean
}

export interface CredentialField {
  key: CredentialKey
  label: string
  placeholder: string
}

export interface ProviderSpec {
  label: string
  /** Providers disagree about what the identifier is called; using their word avoids a guess. */
  modelLabel: string
  modelPlaceholder: string
  modelDescription: string
  connection: ConnectionField[]
  credentials: CredentialField[]
  /** Only Ollama has its reasoning mode wired up, so only Ollama offers the control. */
  thinking?: boolean
}

const AZURE_ENDPOINT: ConnectionField = {
  key: 'endpoint',
  label: 'Resource endpoint',
  placeholder: 'https://your-resource.openai.azure.com',
  description: 'The resource root. No /openai suffix — the SDK adds its own and the call 404s.',
  required: true,
}

const AZURE_API_VERSION: ConnectionField = {
  key: 'api_version',
  label: 'API version',
  placeholder: '2024-10-21',
  description: 'Leave empty unless your resource needs a specific one.',
  required: false,
}

const BEDROCK_REGION: ConnectionField = {
  key: 'region',
  label: 'AWS region',
  placeholder: 'eu-central-1',
  description: 'Where the model is enabled for your account.',
  required: true,
}

const OLLAMA_BASE_URL: ConnectionField = {
  key: 'base_url',
  label: 'Server URL',
  placeholder: 'http://localhost:11434',
  description: 'Reachable from the API and the ingestion worker, not from your browser.',
  required: true,
}

const AWS_CREDENTIALS: CredentialField[] = [
  { key: 'access_key_id', label: 'Access key ID', placeholder: 'AKIA…' },
  { key: 'secret_access_key', label: 'Secret access key', placeholder: '' },
]

export const PROVIDERS: Record<ChatProviderName, ProviderSpec> = {
  azure: {
    label: 'Azure AI Foundry',
    modelLabel: 'Deployment name',
    modelPlaceholder: 'gpt-4.1-mini',
    modelDescription: 'What you named the deployment, which need not match the model.',
    connection: [AZURE_ENDPOINT, AZURE_API_VERSION],
    credentials: [{ key: 'api_key', label: 'API key', placeholder: '' }],
  },
  bedrock: {
    label: 'Amazon Bedrock',
    modelLabel: 'Model ID',
    modelPlaceholder: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
    modelDescription: 'The full Bedrock model identifier.',
    connection: [BEDROCK_REGION],
    credentials: AWS_CREDENTIALS,
  },
  anthropic: {
    label: 'Anthropic',
    modelLabel: 'Model name',
    modelPlaceholder: 'claude-sonnet-4-5',
    modelDescription: 'As published by Anthropic.',
    connection: [],
    credentials: [{ key: 'api_key', label: 'API key', placeholder: 'sk-ant-…' }],
  },
  ollama: {
    label: 'Ollama (self-hosted)',
    modelLabel: 'Model name',
    modelPlaceholder: 'llama3.1',
    modelDescription: 'Already pulled on that server — nothing here downloads it.',
    connection: [OLLAMA_BASE_URL],
    credentials: [],
    thinking: true,
  },
}

/** Chat models for Bedrock; the embedding half wants a different example. */
const EMBEDDING_MODEL_HINTS: Partial<Record<ChatProviderName, Partial<ProviderSpec>>> = {
  azure: { modelPlaceholder: 'text-embedding-3-small' },
  bedrock: { modelPlaceholder: 'amazon.titan-embed-text-v2:0' },
  ollama: { modelPlaceholder: 'nomic-embed-text' },
}

export function specFor(capability: Capability, provider: string): ProviderSpec {
  const base = PROVIDERS[provider as ChatProviderName] ?? PROVIDERS.ollama
  if (capability === 'chat') return base
  return { ...base, ...EMBEDDING_MODEL_HINTS[provider as ChatProviderName], thinking: false }
}

/** `chat_endpoint`, `embedding_api_key` — one flat input per field, as FormData needs. */
export function fieldName(capability: Capability, key: string): string {
  return `${capability}_${key}`
}

export const CONNECTION_KEYS: ConnectionKey[] = ['endpoint', 'api_version', 'region', 'base_url']
export const CREDENTIAL_KEYS: CredentialKey[] = ['api_key', 'access_key_id', 'secret_access_key']

export interface AIConfigValues {
  chat_provider: ChatProviderName
  chat_model: string
  chat_endpoint: string
  chat_api_version: string
  chat_region: string
  chat_base_url: string
  chat_api_key: string
  chat_access_key_id: string
  chat_secret_access_key: string
  chat_think: boolean
  embedding_provider: EmbeddingProviderName
  embedding_model: string
  embedding_endpoint: string
  embedding_api_version: string
  embedding_region: string
  embedding_base_url: string
  embedding_api_key: string
  embedding_access_key_id: string
  embedding_secret_access_key: string
}

const OLLAMA_DEFAULT_URL = 'http://localhost:11434'

/**
 * Credentials are never among these: they are not returned by the API and a blank field is
 * how the form says "keep whatever is stored". Ollama's URL is pre-filled because a form
 * that is valid on arrival can be tested before anything has been typed into it.
 */
export function aiConfigDefaults(config: AIConfig | null): AIConfigValues {
  return {
    chat_provider: (config?.chat.provider as ChatProviderName) ?? 'ollama',
    chat_model: config?.chat.model ?? '',
    ...connectionDefaults('chat', config?.chat),
    chat_api_key: '',
    chat_access_key_id: '',
    chat_secret_access_key: '',
    chat_think: readThink(config?.chat),
    embedding_provider: (config?.embedding.provider as EmbeddingProviderName) ?? 'ollama',
    embedding_model: config?.embedding.model ?? '',
    ...connectionDefaults('embedding', config?.embedding),
    embedding_api_key: '',
    embedding_access_key_id: '',
    embedding_secret_access_key: '',
  } as AIConfigValues
}

function connectionDefaults(capability: Capability, half: ProviderRead | undefined) {
  const stored = (half?.connection ?? {}) as Record<string, unknown>
  const provider = half?.provider ?? 'ollama'
  const text = (key: ConnectionKey) => (typeof stored[key] === 'string' ? stored[key] : '')

  return {
    [`${capability}_endpoint`]: text('endpoint'),
    [`${capability}_api_version`]: text('api_version'),
    [`${capability}_region`]: text('region'),
    [`${capability}_base_url`]:
      text('base_url') || (provider === 'ollama' ? OLLAMA_DEFAULT_URL : ''),
  }
}

function readThink(half: ProviderRead | undefined): boolean {
  const value = (half?.connection as Record<string, unknown> | undefined)?.think
  // Absent means on, matching the column's default rather than guessing from the provider.
  return typeof value === 'boolean' ? value : true
}
