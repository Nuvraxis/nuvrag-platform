'use server'

import { ApiError } from '@rag/api-client'
import { redirect } from 'next/navigation'

import { type ActionState, failed, fromError } from '@/lib/action-state'
import { publicApi } from '@/lib/api'
import { clearSession, readRefreshToken, writeSession } from '@/lib/session'

/**
 * `?next=` comes from the middleware redirect and ends up in a hidden input, so it is
 * attacker-controllable. Only same-origin absolute paths are honoured; anything else
 * (`//evil.example`, `https://…`) falls back to the default landing page.
 */
function safeRedirect(target: FormDataEntryValue | null): string {
  const value = typeof target === 'string' ? target : ''
  return value.startsWith('/') && !value.startsWith('//') ? value : '/chatbots'
}

function text(formData: FormData, name: string): string {
  const value = formData.get(name)
  return typeof value === 'string' ? value.trim() : ''
}

export async function loginAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const email = text(formData, 'email')
  const password = String(formData.get('password') ?? '')

  if (!email || !password) {
    return failed('Enter your email and password.')
  }

  try {
    const tokens = await publicApi().login({ email, password })
    await writeSession(tokens)
  } catch (error) {
    // `fromError` reads a 401 as a session that has run out, which is right everywhere else
    // in the dashboard. On the sign-in form there is no session yet — only credentials that
    // do not match — and telling someone to sign in again is no help at all.
    if (error instanceof ApiError && error.isUnauthorized) {
      return failed('That email and password do not match.')
    }
    return fromError(error)
  }

  redirect(safeRedirect(formData.get('next')))
}

export async function signupAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const organizationName = text(formData, 'organization_name')
  const email = text(formData, 'email')
  const fullName = text(formData, 'full_name')
  const password = String(formData.get('password') ?? '')

  if (!organizationName || !email || !password) {
    return failed('Organisation, email and password are all required.')
  }

  try {
    const response = await publicApi().signup({
      organization_name: organizationName,
      email,
      password,
      full_name: fullName || null,
    })
    await writeSession(response.tokens)
  } catch (error) {
    return fromError(error)
  }

  redirect('/chatbots')
}

export async function logoutAction(): Promise<void> {
  const refreshToken = await readRefreshToken()

  if (refreshToken) {
    try {
      // Retires the token server-side. Without this, clearing the cookie only forgets the
      // session locally — the token itself stays valid until it expires.
      await publicApi().logout(refreshToken)
    } catch {
      // An API that cannot be reached must not trap someone on a page they want to leave.
      // The cookie still goes.
    }
  }

  await clearSession()
  redirect('/login')
}

export async function acceptInvitationAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const token = text(formData, 'token')
  const password = String(formData.get('password') ?? '')

  if (!token) {
    return failed('This invitation link is missing its token.')
  }
  if (!password) {
    return failed('Choose a password to finish setting up your account.')
  }

  try {
    const response = await publicApi().acceptInvitation({
      token,
      password,
      full_name: text(formData, 'full_name') || null,
    })
    await writeSession(response.tokens)
  } catch (error) {
    return fromError(error)
  }

  redirect('/chatbots')
}
