/**
 * Reads the `exp` claim without verifying the signature.
 *
 * The dashboard only needs to know when to ask for a refresh; the API verifies every token
 * it is given, so trusting this locally costs nothing. A tampered token simply fails there.
 */
export function tokenExpiry(token: string): number | null {
  const payload = token.split('.')[1]
  if (!payload) return null

  try {
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    const claims = JSON.parse(json) as { exp?: unknown }
    return typeof claims.exp === 'number' ? claims.exp : null
  } catch {
    return null
  }
}

/**
 * True when the token is past its expiry, or close enough that a request made now could
 * arrive after it. Anything unparseable counts as expired so the caller re-authenticates
 * rather than sending a token the API will reject.
 */
export function isExpired(token: string, skewSeconds = 30): boolean {
  const exp = tokenExpiry(token)
  if (exp === null) return true
  return exp - skewSeconds <= Math.floor(Date.now() / 1000)
}

/** Seconds until expiry, floored at zero, for use as a cookie `maxAge`. */
export function secondsUntilExpiry(token: string, fallbackSeconds: number): number {
  const exp = tokenExpiry(token)
  if (exp === null) return fallbackSeconds
  return Math.max(0, exp - Math.floor(Date.now() / 1000))
}
