import type {
  AcceptInvitationRequest,
  AcceptInvitationResponse,
  AIConfig,
  AIConfigTest,
  AIConfigTestResult,
  AIConfigUpdate,
  Chatbot,
  ChatbotAnalytics,
  ChatbotCreate,
  ChatbotCreateResponse,
  ChatbotSecret,
  ChatbotStatus,
  ChatbotUpdate,
  Conversation,
  Document,
  DocumentStatus,
  DocumentUploadResponse,
  EmbedSnippet,
  HealthResponse,
  Invitation,
  InvitationCreate,
  InvitationCreated,
  InvitationPreview,
  InvitationStatus,
  LoginRequest,
  MemberUpdate,
  MemoryCalibration,
  Message,
  Page,
  SignupRequest,
  SignupResponse,
  TeamMembers,
  Ticket,
  TicketDetail,
  TicketReply,
  TicketStatus,
  TicketUpdate,
  TokenPair,
  User,
} from '@rag/types'

import { ApiUnreachableError, errorFromResponse } from './errors'

export interface ApiClientOptions {
  baseUrl: string
  /** Dashboard access token. Read per request so a refreshed token is picked up. */
  token?: string | null
  /** Injected in tests; defaults to the platform `fetch`. */
  fetch?: typeof globalThis.fetch
  /** Applies to every call except uploads, which get their own longer budget. */
  timeoutMs?: number
}

export interface RequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
  /** Passed through to Next.js's extended `fetch` for route-level caching. */
  cache?: RequestCache
}

// A type alias rather than an interface: only aliases get an implicit index signature, which
// is what lets a query object be passed straight to the serialiser below.
export type PageQuery = {
  limit?: number
  offset?: number
}

const DEFAULT_TIMEOUT_MS = 15_000
const UPLOAD_TIMEOUT_MS = 120_000

type QueryValue = string | number | boolean | null | undefined

export class ApiClient {
  private readonly baseUrl: string
  private readonly token: string | null
  private readonly fetchImpl: typeof globalThis.fetch
  private readonly timeoutMs: number

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.token = options.token ?? null
    this.fetchImpl = options.fetch ?? globalThis.fetch
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  }

  /** A copy of this client bound to a different token, for use after a refresh. */
  withToken(token: string | null): ApiClient {
    return new ApiClient({
      baseUrl: this.baseUrl,
      token,
      fetch: this.fetchImpl,
      timeoutMs: this.timeoutMs,
    })
  }

  /* ---------------------------------------------------------------- auth -- */

  signup(body: SignupRequest, options?: RequestOptions): Promise<SignupResponse> {
    return this.send('POST', '/api/v1/auth/signup', { body, ...options })
  }

  login(body: LoginRequest, options?: RequestOptions): Promise<TokenPair> {
    return this.send('POST', '/api/v1/auth/login', { body, ...options })
  }

  refresh(refreshToken: string, options?: RequestOptions): Promise<TokenPair> {
    return this.send('POST', '/api/v1/auth/refresh', {
      body: { refresh_token: refreshToken },
      ...options,
    })
  }

  me(options?: RequestOptions): Promise<User> {
    return this.send('GET', '/api/v1/auth/me', options)
  }

  async logout(refreshToken: string, options?: RequestOptions): Promise<void> {
    await this.send('POST', '/api/v1/auth/logout', {
      body: { refresh_token: refreshToken },
      ...options,
    })
  }

  previewInvitation(token: string, options?: RequestOptions): Promise<InvitationPreview> {
    return this.send('GET', '/api/v1/auth/invitations/preview', { query: { token }, ...options })
  }

  acceptInvitation(
    body: AcceptInvitationRequest,
    options?: RequestOptions,
  ): Promise<AcceptInvitationResponse> {
    return this.send('POST', '/api/v1/auth/invitations/accept', { body, ...options })
  }

  /* ---------------------------------------------------------------- team -- */

  listMembers(options?: RequestOptions): Promise<TeamMembers> {
    return this.send('GET', '/api/v1/team/members', options)
  }

  updateMember(userId: string, body: MemberUpdate, options?: RequestOptions): Promise<User> {
    return this.send('PATCH', `/api/v1/team/members/${encode(userId)}`, { body, ...options })
  }

  async removeMember(userId: string, options?: RequestOptions): Promise<void> {
    await this.send('DELETE', `/api/v1/team/members/${encode(userId)}`, options)
  }

  createInvitation(body: InvitationCreate, options?: RequestOptions): Promise<InvitationCreated> {
    return this.send('POST', '/api/v1/team/invitations', { body, ...options })
  }

  listInvitations(
    query: { status?: InvitationStatus } = {},
    options?: RequestOptions,
  ): Promise<Invitation[]> {
    return this.send('GET', '/api/v1/team/invitations', { query, ...options })
  }

  revokeInvitation(invitationId: string, options?: RequestOptions): Promise<Invitation> {
    return this.send('DELETE', `/api/v1/team/invitations/${encode(invitationId)}`, options)
  }

  /* ------------------------------------------------------------ chatbots -- */

  listChatbots(
    query: PageQuery & { status?: ChatbotStatus } = {},
    options?: RequestOptions,
  ): Promise<Page<Chatbot>> {
    return this.send('GET', '/api/v1/chatbots', { query, ...options })
  }

  createChatbot(body: ChatbotCreate, options?: RequestOptions): Promise<ChatbotCreateResponse> {
    return this.send('POST', '/api/v1/chatbots', { body, ...options })
  }

  getChatbot(chatbotId: string, options?: RequestOptions): Promise<Chatbot> {
    return this.send('GET', `/api/v1/chatbots/${encode(chatbotId)}`, options)
  }

  updateChatbot(
    chatbotId: string,
    body: ChatbotUpdate,
    options?: RequestOptions,
  ): Promise<Chatbot> {
    return this.send('PATCH', `/api/v1/chatbots/${encode(chatbotId)}`, { body, ...options })
  }

  async deleteChatbot(chatbotId: string, options?: RequestOptions): Promise<void> {
    await this.send('DELETE', `/api/v1/chatbots/${encode(chatbotId)}`, options)
  }

  rotateSecret(chatbotId: string, options?: RequestOptions): Promise<ChatbotSecret> {
    return this.send('POST', `/api/v1/chatbots/${encode(chatbotId)}/rotate-secret`, options)
  }

  memoryCalibration(chatbotId: string, options?: RequestOptions): Promise<MemoryCalibration> {
    return this.send('GET', `/api/v1/chatbots/${encode(chatbotId)}/memory-calibration`, options)
  }

  /** POST rather than GET: it calls the chatbot's embedding provider to take a measurement. */
  recalibrateMemory(chatbotId: string, options?: RequestOptions): Promise<MemoryCalibration> {
    return this.send('POST', `/api/v1/chatbots/${encode(chatbotId)}/memory-calibration`, options)
  }

  embedSnippet(chatbotId: string, options?: RequestOptions): Promise<EmbedSnippet> {
    return this.send('GET', `/api/v1/chatbots/${encode(chatbotId)}/embed-snippet`, options)
  }

  analytics(
    chatbotId: string,
    query: { days?: number } = {},
    options?: RequestOptions,
  ): Promise<ChatbotAnalytics> {
    return this.send('GET', `/api/v1/chatbots/${encode(chatbotId)}/analytics`, {
      query,
      ...options,
    })
  }

  /* --------------------------------------------------------- ai providers -- */

  /** 404s until a provider has been chosen, which is a state the dashboard renders. */
  getAIConfig(chatbotId: string, options?: RequestOptions): Promise<AIConfig> {
    return this.send('GET', `/api/v1/chatbots/${encode(chatbotId)}/ai-config`, options)
  }

  updateAIConfig(
    chatbotId: string,
    body: AIConfigUpdate,
    options?: RequestOptions,
  ): Promise<AIConfig> {
    return this.send('PUT', `/api/v1/chatbots/${encode(chatbotId)}/ai-config`, {
      body,
      ...options,
    })
  }

  /**
   * Always resolves on a reachable API: a provider rejecting a key is reported in the body
   * rather than as a failed request. It calls out to someone else's service, so it gets the
   * upload budget rather than the default one.
   */
  testAIConfig(
    chatbotId: string,
    body: AIConfigTest,
    options?: RequestOptions,
  ): Promise<AIConfigTestResult> {
    return this.send('POST', `/api/v1/chatbots/${encode(chatbotId)}/ai-config/test`, {
      body,
      ...options,
      timeoutMs: options?.timeoutMs ?? UPLOAD_TIMEOUT_MS,
    })
  }

  /* ----------------------------------------------------------- documents -- */

  listDocuments(
    chatbotId: string,
    query: PageQuery & { status?: DocumentStatus } = {},
    options?: RequestOptions,
  ): Promise<Page<Document>> {
    return this.send('GET', `/api/v1/chatbots/${encode(chatbotId)}/documents`, {
      query,
      ...options,
    })
  }

  uploadDocument(
    chatbotId: string,
    file: File,
    options?: RequestOptions,
  ): Promise<DocumentUploadResponse> {
    const form = new FormData()
    form.append('file', file, file.name)
    return this.send('POST', `/api/v1/chatbots/${encode(chatbotId)}/documents`, {
      ...options,
      body: form,
      timeoutMs: options?.timeoutMs ?? UPLOAD_TIMEOUT_MS,
    })
  }

  getDocument(chatbotId: string, documentId: string, options?: RequestOptions): Promise<Document> {
    return this.send(
      'GET',
      `/api/v1/chatbots/${encode(chatbotId)}/documents/${encode(documentId)}`,
      options,
    )
  }

  reprocessDocument(
    chatbotId: string,
    documentId: string,
    options?: RequestOptions,
  ): Promise<{ document_id: string; task_id: string | null }> {
    return this.send(
      'POST',
      `/api/v1/chatbots/${encode(chatbotId)}/documents/${encode(documentId)}/reprocess`,
      options,
    )
  }

  async deleteDocument(
    chatbotId: string,
    documentId: string,
    options?: RequestOptions,
  ): Promise<void> {
    await this.send(
      'DELETE',
      `/api/v1/chatbots/${encode(chatbotId)}/documents/${encode(documentId)}`,
      options,
    )
  }

  /* ------------------------------------------------------- conversations -- */

  listConversations(
    chatbotId: string,
    query: PageQuery = {},
    options?: RequestOptions,
  ): Promise<Page<Conversation>> {
    return this.send('GET', `/api/v1/chatbots/${encode(chatbotId)}/conversations`, {
      query,
      ...options,
    })
  }

  listMessages(
    chatbotId: string,
    conversationId: string,
    query: PageQuery = {},
    options?: RequestOptions,
  ): Promise<Page<Message>> {
    return this.send(
      'GET',
      `/api/v1/chatbots/${encode(chatbotId)}/conversations/${encode(conversationId)}/messages`,
      { query, ...options },
    )
  }

  /** Irreversible, and it takes the messages and any ticket with it. Admin or above. */
  async deleteConversation(
    chatbotId: string,
    conversationId: string,
    options?: RequestOptions,
  ): Promise<void> {
    await this.send(
      'DELETE',
      `/api/v1/chatbots/${encode(chatbotId)}/conversations/${encode(conversationId)}`,
      options,
    )
  }

  /* ------------------------------------------------------------- tickets -- */

  listTickets(
    query: PageQuery & {
      chatbot_id?: string
      status?: TicketStatus
      assigned_to?: string
    } = {},
    options?: RequestOptions,
  ): Promise<Page<Ticket>> {
    return this.send('GET', '/api/v1/tickets', { query, ...options })
  }

  /** Returns the ticket together with the conversation it wraps. */
  getTicket(ticketId: string, options?: RequestOptions): Promise<TicketDetail> {
    return this.send('GET', `/api/v1/tickets/${encode(ticketId)}`, options)
  }

  updateTicket(ticketId: string, body: TicketUpdate, options?: RequestOptions): Promise<Ticket> {
    return this.send('PATCH', `/api/v1/tickets/${encode(ticketId)}`, { body, ...options })
  }

  /**
   * Erases everything remembered about this ticket's visitor.
   *
   * Keyed on the ticket rather than on the visitor, because the subject of a note is their
   * session id — a bearer capability the dashboard is deliberately never given.
   */
  async forgetVisitorMemory(ticketId: string, options?: RequestOptions): Promise<void> {
    await this.send('DELETE', `/api/v1/tickets/${encode(ticketId)}/memory`, options)
  }

  /** Appends a staff reply to the ticket's conversation as a `role='staff'` message. */
  replyToTicket(ticketId: string, body: TicketReply, options?: RequestOptions): Promise<Message> {
    return this.send('POST', `/api/v1/tickets/${encode(ticketId)}/messages`, {
      body,
      ...options,
    })
  }

  /* -------------------------------------------------------------- health -- */

  health(options?: RequestOptions): Promise<HealthResponse> {
    return this.send('GET', '/health/ready', options)
  }

  /* ------------------------------------------------------------ internals -- */

  private async send<ResultT>(
    method: string,
    path: string,
    options: RequestOptions & { body?: unknown; query?: Record<string, QueryValue> } = {},
  ): Promise<ResultT> {
    const url = this.baseUrl + path + buildQuery(options.query)
    const headers: Record<string, string> = { accept: 'application/json' }
    if (this.token) {
      headers.authorization = `Bearer ${this.token}`
    }

    let payload: BodyInit | undefined
    if (options.body instanceof FormData) {
      // Deliberately no content-type: the runtime has to add the multipart boundary.
      payload = options.body
    } else if (options.body !== undefined) {
      headers['content-type'] = 'application/json'
      payload = JSON.stringify(options.body)
    }

    const response = await this.dispatch(url, {
      method,
      headers,
      body: payload,
      cache: options.cache,
      signal: withTimeout(options.signal, options.timeoutMs ?? this.timeoutMs),
    })

    if (!response.ok) {
      throw await errorFromResponse(response)
    }
    if (response.status === 204 || response.headers.get('content-length') === '0') {
      return undefined as ResultT
    }
    return (await response.json()) as ResultT
  }

  private async dispatch(url: string, init: RequestInit): Promise<Response> {
    try {
      return await this.fetchImpl(url, init)
    } catch (cause) {
      // `fetch` rejects only when the request never produced a response, so this is always a
      // transport problem — worth distinguishing from an API error the UI can explain.
      throw new ApiUnreachableError(url, cause)
    }
  }
}

function encode(segment: string): string {
  return encodeURIComponent(segment)
}

function buildQuery(query?: Record<string, QueryValue>): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

function withTimeout(signal: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeout = AbortSignal.timeout(timeoutMs)
  return signal ? AbortSignal.any([signal, timeout]) : timeout
}
