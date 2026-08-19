import type { ApiErrorBody, ValidationFailure } from '@rag/types'

/** A non-2xx response, carrying the backend's `{error: {code, message, details}}` envelope. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }

  get isNotFound(): boolean {
    return this.status === 404
  }

  /** Field-level failures from a 422, empty for every other status. */
  get fieldErrors(): ValidationFailure[] {
    const errors = this.details.errors
    return Array.isArray(errors) ? (errors as ValidationFailure[]) : []
  }

  /** `{password: "Password must be at least 10 characters"}`, ready to hand to a form. */
  toFieldMap(): Record<string, string> {
    const map: Record<string, string> = {}
    for (const failure of this.fieldErrors) {
      map[failure.field] ??= failure.message
    }
    return map
  }
}

/** The request never reached the API — DNS, TLS, connection refused, or a timeout. */
export class ApiUnreachableError extends Error {
  constructor(url: string, cause: unknown) {
    super(`Could not reach the API at ${url}`)
    this.name = 'ApiUnreachableError'
    this.cause = cause
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError
}

export async function errorFromResponse(response: Response): Promise<ApiError> {
  const fallback = `Request failed with status ${response.status}`
  let body: unknown

  try {
    body = await response.json()
  } catch {
    // An error page from a proxy, or an empty body on a 502 — neither is JSON.
    return new ApiError(response.status, 'http_error', fallback, {})
  }

  const envelope = (body as Partial<ApiErrorBody>).error
  if (!envelope) {
    return new ApiError(response.status, 'http_error', fallback, {})
  }

  return new ApiError(
    response.status,
    envelope.code ?? 'http_error',
    envelope.message || fallback,
    envelope.details ?? {},
  )
}
