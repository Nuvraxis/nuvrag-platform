/**
 * Hand-written aliases over the generated OpenAPI schema.
 *
 * `src/schema.d.ts` is regenerated from the backend (see the package README), so renaming a
 * Pydantic model or dropping a field breaks the build here rather than producing `undefined`
 * somewhere in a React tree.
 */
import type { components, operations, paths } from './schema'

export type { components, operations, paths }

type Schemas = components['schemas']

/* Identity */
export type Organization = Schemas['OrganizationRead']
export type User = Schemas['UserRead']
export type UserRole = Schemas['UserRole']
export type Plan = Schemas['Plan']
export type TokenPair = Schemas['TokenPair']
export type SignupRequest = Schemas['SignupRequest']
export type SignupResponse = Schemas['SignupResponse']
export type LoginRequest = Schemas['LoginRequest']

/* Team */
export type Invitation = Schemas['InvitationRead']
export type InvitationCreate = Schemas['InvitationCreate']
export type InvitationCreated = Schemas['InvitationCreated']
export type InvitationPreview = Schemas['InvitationPreview']
export type InvitationStatus = Schemas['InvitationStatus']
export type MemberUpdate = Schemas['MemberUpdate']
export type TeamMembers = Schemas['TeamMembers']
export type AcceptInvitationRequest = Schemas['AcceptInvitationRequest']
export type AcceptInvitationResponse = Schemas['AcceptInvitationResponse']

/* Chatbots */
export type Chatbot = Schemas['ChatbotRead']
export type ChatbotCreate = Schemas['ChatbotCreate']
export type ChatbotCreateResponse = Schemas['ChatbotCreateResponse']
export type ChatbotUpdate = Schemas['ChatbotUpdate']
export type ChatbotSecret = Schemas['ChatbotSecret']
export type ChatbotStatus = Schemas['ChatbotStatus']
export type GenerationConfig = Schemas['GenerationConfig']
export type WidgetTheme = Schemas['WidgetTheme']
export type EmbedSnippet = Schemas['EmbedSnippet']
export type MemoryCalibration = Schemas['MemoryCalibrationRead']
export type UsagePeriod = Schemas['UsagePeriodRead']

/* AI providers */
export type AIConfig = Schemas['AIConfigRead']
export type AIConfigUpdate = Schemas['AIConfigUpdate']
export type AIConfigTest = Schemas['AIConfigTest']
export type AIConfigTestResult = Schemas['AIConfigTestResult']
export type ProviderRead = Schemas['ProviderRead']
export type ProviderConnection = Schemas['ProviderConnection']
export type ChatConnection = Schemas['ChatConnection']
export type ProviderCredentials = Schemas['ProviderCredentials']
export type ChatTarget = Schemas['ChatTarget']
export type EmbeddingTarget = Schemas['EmbeddingTarget']
export type ChatProviderName = Schemas['ChatProviderName']
export type EmbeddingProviderName = Schemas['EmbeddingProviderName']

/* Documents */
export type Document = Schemas['DocumentRead']
export type DocumentStatus = Schemas['DocumentStatus']
export type DocumentUploadResponse = Schemas['DocumentUploadResponse']
export type FileType = Schemas['FileType']

/* Conversations */
export type Conversation = Schemas['ConversationRead']
export type Message = Schemas['MessageRead']
export type MessageRole = Schemas['MessageRole']

/* Tickets */
export type Ticket = Schemas['TicketRead']
export type TicketDetail = Schemas['TicketDetail']
export type TicketUpdate = Schemas['TicketUpdate']
export type TicketReply = Schemas['TicketReply']
export type TicketStatus = Schemas['TicketStatus']
export type TicketPriority = Schemas['TicketPriority']
export type TicketSource = Schemas['TicketSource']

/* Analytics */
export type ChatbotAnalytics = Schemas['ChatbotAnalytics']
export type DocumentTotals = Schemas['DocumentTotals']
export type MessageTotals = Schemas['MessageTotals']
export type DailyActivityPoint = Schemas['DailyActivityPoint']

/* Health */
export type HealthResponse = Schemas['HealthResponse']

/**
 * The backend's `Page[ItemT]` is emitted once per concrete item type, so the generic shape
 * is restated here. The assertion below fails to compile if the two ever diverge.
 */
export interface Page<ItemT> {
  items: ItemT[]
  total: number
  limit: number
  offset: number
}

type AssertAssignable<Expected, Actual extends Expected> = Actual
type _PageShapeMatchesBackend = AssertAssignable<Page<Chatbot>, Schemas['Page_ChatbotRead_']>

/**
 * A passage the model cited, denormalised onto the message row as `sources_json`.
 *
 * Written by hand because the backend streams it over SSE rather than returning it from a
 * declared response model, so OpenAPI never sees it. It mirrors `SourceRead` in
 * `app/schemas/chat.py`.
 */
export interface CitedSource {
  marker: number
  chunk_id: string
  document_id: string
  similarity: number
  excerpt: string
  metadata: Record<string, unknown>
}

/** Shape of the JSON body every error handler in `app/api/errors.py` returns. */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details: Record<string, unknown>
  }
}

/** One entry of `details.errors` on a 422. */
export interface ValidationFailure {
  field: string
  type: string
  message: string
}

export const DOCUMENT_STATUSES = ['pending', 'processing', 'ready', 'failed'] as const
export const CHATBOT_STATUSES = ['active', 'paused', 'archived'] as const
/** Ordered as the queue is worked: new, in hand, done, filed away. */
export const TICKET_STATUSES = ['open', 'pending', 'resolved', 'closed'] as const
export const TICKET_PRIORITIES = ['low', 'normal', 'high', 'urgent'] as const
/** Ordered least to most privileged, which is the order the role pickers present them in. */
export const USER_ROLES = ['member', 'admin', 'owner'] as const
/** Extensions the ingestion pipeline has an extractor for. */
export const UPLOAD_EXTENSIONS = ['.pdf', '.docx', '.md', '.mdx', '.txt'] as const

export const CHAT_PROVIDERS = ['azure', 'bedrock', 'anthropic', 'ollama'] as const
/**
 * No Anthropic: it publishes no embeddings API. The assertions below fail to compile if
 * either list drifts from the enum the backend generated, which is what stops a picker
 * offering something the API will refuse.
 */
export const EMBEDDING_PROVIDERS = ['azure', 'bedrock', 'ollama'] as const

type _ChatProvidersMatchBackend = AssertAssignable<
  ChatProviderName,
  (typeof CHAT_PROVIDERS)[number]
>
type _EmbeddingProvidersMatchBackend = AssertAssignable<
  EmbeddingProviderName,
  (typeof EMBEDDING_PROVIDERS)[number]
>

type _TicketStatusesMatchBackend = AssertAssignable<TicketStatus, (typeof TICKET_STATUSES)[number]>
type _TicketPrioritiesMatchBackend = AssertAssignable<
  TicketPriority,
  (typeof TICKET_PRIORITIES)[number]
>
