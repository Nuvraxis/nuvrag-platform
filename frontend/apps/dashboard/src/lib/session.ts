import type { TokenPair } from '@rag/api-client'
import { cookies } from 'next/headers'

import { secondsUntilExpiry } from './jwt'

export const ACCESS_COOKIE = 'rag_access'
export const REFRESH_COOKIE = 'rag_refresh'

/** Matches the backend defaults; only used if a token carries no readable `exp`. */
const ACCESS_FALLBACK_SECONDS = 15 * 60
const REFRESH_FALLBACK_SECONDS = 14 * 24 * 60 * 60

export interface CookieAttributes {
  httpOnly: true
  sameSite: 'lax'
  secure: boolean
  path: string
  maxAge: number
}

/**
 * `httpOnly` keeps the tokens out of reach of any script on the page, which is the whole
 * point of proxying the API through the server rather than calling it from the browser.
 * `sameSite=lax` still allows the top-level navigation back from an email link.
 */
export function cookieAttributes(maxAge: number): CookieAttributes {
  return {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge,
  }
}

export function accessCookieAttributes(token: string): CookieAttributes {
  return cookieAttributes(secondsUntilExpiry(token, ACCESS_FALLBACK_SECONDS))
}

export function refreshCookieAttributes(token: string): CookieAttributes {
  return cookieAttributes(secondsUntilExpiry(token, REFRESH_FALLBACK_SECONDS))
}

export async function readAccessToken(): Promise<string | null> {
  const store = await cookies()
  return store.get(ACCESS_COOKIE)?.value ?? null
}

export async function readRefreshToken(): Promise<string | null> {
  const store = await cookies()
  return store.get(REFRESH_COOKIE)?.value ?? null
}

/** Only callable from a Server Action or Route Handler — Server Components cannot set cookies. */
export async function writeSession(tokens: TokenPair): Promise<void> {
  const store = await cookies()
  store.set(ACCESS_COOKIE, tokens.access_token, accessCookieAttributes(tokens.access_token))
  store.set(REFRESH_COOKIE, tokens.refresh_token, refreshCookieAttributes(tokens.refresh_token))
}

export async function clearSession(): Promise<void> {
  const store = await cookies()
  store.delete(ACCESS_COOKIE)
  store.delete(REFRESH_COOKIE)
}
