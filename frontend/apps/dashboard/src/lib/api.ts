import 'server-only'

import { ApiClient, isApiError } from '@rag/api-client'
import { notFound, redirect } from 'next/navigation'

import { env } from './env'
import { readAccessToken } from './session'

/** Unauthenticated client, for signup and login. */
export function publicApi(): ApiClient {
  return new ApiClient({ baseUrl: env.apiBaseUrl })
}

export async function authenticatedApi(): Promise<ApiClient> {
  const token = await readAccessToken()
  if (!token) {
    redirect('/login')
  }
  return new ApiClient({ baseUrl: env.apiBaseUrl, token })
}

/**
 * Runs an authenticated call on behalf of a page.
 *
 * A rejected token becomes a trip back to sign-in: the proxy refreshes tokens before the
 * request reaches a page, so a 401 here means the session is genuinely over. A 404 becomes
 * the not-found page, since every id in a URL is tenant-scoped — "missing" and "belongs to
 * someone else" are the same answer, and should look the same.
 */
export async function fetchApi<ResultT>(
  call: (api: ApiClient) => Promise<ResultT>,
): Promise<ResultT> {
  const api = await authenticatedApi()
  try {
    return await call(api)
  } catch (error) {
    if (isApiError(error)) {
      if (error.isUnauthorized) redirect('/login')
      if (error.isNotFound) notFound()
    }
    throw error
  }
}
