import type { TokenPair } from '@rag/api-client'
import { type NextRequest, NextResponse } from 'next/server'

import { env } from '@/lib/env'
import { isExpired } from '@/lib/jwt'
import {
  ACCESS_COOKIE,
  accessCookieAttributes,
  REFRESH_COOKIE,
  refreshCookieAttributes,
} from '@/lib/session'

/**
 * Gatekeeper for every dashboard request.
 *
 * Access tokens live fifteen minutes, so refreshing them lazily on a 401 would mean a failed
 * render — and a Server Component cannot write the replacement cookie anyway. Doing it here
 * means the page below always sees a usable token, and the browser gets the new one on the
 * same response.
 *
 * This is `proxy.ts` rather than `middleware.ts` because Next runs the former on the Node.js
 * runtime, where `API_BASE_URL` is read from the container's environment at start-up instead
 * of being inlined into an edge bundle at build time.
 */

/** Pointless to visit while signed in, so a session bounces off them. */
const SIGNED_OUT_PATHS = ['/login', '/signup']
/**
 * Reachable either way. Accepting an invitation must work while signed in as someone else —
 * bouncing that visitor to the dashboard would strand the link they were sent.
 */
const PUBLIC_PATHS = ['/accept-invitation']
const LANDING_PATH = '/chatbots'

function matches(pathname: string, paths: readonly string[]): boolean {
  return paths.some((path) => pathname === path || pathname.startsWith(`${path}/`))
}

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl
  const isSignedOutPath = matches(pathname, SIGNED_OUT_PATHS)
  const isPublicPath = isSignedOutPath || matches(pathname, PUBLIC_PATHS)

  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value ?? null
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value ?? null
  let renewed: TokenPair | null = null

  if ((!accessToken || isExpired(accessToken)) && refreshToken && !isExpired(refreshToken)) {
    renewed = await renew(refreshToken)
    accessToken = renewed?.access_token ?? null
  }

  const signedIn = accessToken !== null && !isExpired(accessToken)

  if (!signedIn && !isPublicPath) {
    return endSession(request, pathname + search)
  }

  if (signedIn && isSignedOutPath) {
    const destination = request.nextUrl.clone()
    destination.pathname = LANDING_PATH
    destination.search = ''
    return withRenewedCookies(NextResponse.redirect(destination), renewed)
  }

  const headers = new Headers(request.headers)
  if (renewed) {
    // Rewriting the inbound cookie is what lets the page render with the token that was
    // obtained a few lines ago rather than the stale one the browser sent.
    request.cookies.set(ACCESS_COOKIE, renewed.access_token)
    headers.set('cookie', request.cookies.toString())
  }

  const nonce = crypto.randomUUID().replaceAll('-', '')
  const policy = contentSecurityPolicy(nonce)
  headers.set('x-nonce', nonce)
  headers.set('content-security-policy', policy)

  const response = withRenewedCookies(NextResponse.next({ request: { headers } }), renewed)
  response.headers.set('content-security-policy', policy)
  return response
}

async function renew(refreshToken: string): Promise<TokenPair | null> {
  try {
    const response = await fetch(`${env.apiBaseUrl}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    })
    return response.ok ? ((await response.json()) as TokenPair) : null
  } catch {
    // A refresh that cannot reach the API is indistinguishable here from a rejected one.
    // Treating both as "signed out" is the safe reading; the user simply logs in again.
    return null
  }
}

function withRenewedCookies(response: NextResponse, renewed: TokenPair | null): NextResponse {
  if (renewed) {
    response.cookies.set(
      ACCESS_COOKIE,
      renewed.access_token,
      accessCookieAttributes(renewed.access_token),
    )
    response.cookies.set(
      REFRESH_COOKIE,
      renewed.refresh_token,
      refreshCookieAttributes(renewed.refresh_token),
    )
  }
  return response
}

function endSession(request: NextRequest, attempted: string): NextResponse {
  const destination = request.nextUrl.clone()
  destination.pathname = '/login'
  destination.search = attempted === '/' ? '' : `?next=${encodeURIComponent(attempted)}`

  const response = NextResponse.redirect(destination)
  // Clearing both cookies stops an expired pair from re-triggering a doomed refresh on
  // every subsequent request.
  response.cookies.delete(ACCESS_COOKIE)
  response.cookies.delete(REFRESH_COOKIE)
  return response
}

function contentSecurityPolicy(nonce: string): string {
  // The dev server compiles with `eval`, and Turbopack injects its client without a nonce.
  const scriptSources =
    process.env.NODE_ENV === 'production'
      ? `'self' 'nonce-${nonce}' 'strict-dynamic'`
      : `'self' 'unsafe-eval' 'unsafe-inline'`

  return [
    "default-src 'self'",
    `script-src ${scriptSources}`,
    // React and Tailwind both emit inline style attributes; no nonce mechanism covers those.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
  ].join('; ')
}

export const config = {
  matcher: [
    /*
     * Everything except Next's own asset routes and the favicon. Those are static, carry no
     * session, and would only pay the refresh check for nothing.
     */
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
}
