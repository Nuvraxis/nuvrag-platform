'use server'

import type { UserRole } from '@rag/api-client'
import { USER_ROLES } from '@rag/types'
import { revalidatePath } from 'next/cache'

import { type ActionState, failed, fromError, succeeded } from '@/lib/action-state'
import { authenticatedApi } from '@/lib/api'
import { text } from '@/lib/form'

/** The accept link exists only in the response that created the invitation. */
export interface IssuedInvitation {
  email: string
  role: UserRole
  acceptUrl: string
}

const TEAM_PATH = '/team'

function role(formData: FormData, name: string): UserRole | null {
  const value = text(formData, name)
  return (USER_ROLES as readonly string[]).includes(value) ? (value as UserRole) : null
}

export async function inviteMemberAction(
  _previous: ActionState<IssuedInvitation>,
  formData: FormData,
): Promise<ActionState<IssuedInvitation>> {
  const email = text(formData, 'email').toLowerCase()
  const requested = role(formData, 'role') ?? 'member'

  if (!email) {
    return failed('Enter the email address to invite.', { email: 'An email address is required.' })
  }

  const api = await authenticatedApi()
  try {
    const created = await api.createInvitation({ email, role: requested })
    revalidatePath(TEAM_PATH)
    return succeeded(`Invitation ready for ${email}.`, {
      email: created.invitation.email,
      role: created.invitation.role,
      acceptUrl: created.accept_url,
    })
  } catch (error) {
    return fromError(error)
  }
}

// The four below report through `ActionState` rather than returning void. The API refuses
// several of these on purpose — the last active owner, your own account — and a rejection
// that only threw would replace the page with the error boundary instead of saying why.

export async function updateMemberRoleAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const userId = text(formData, 'user_id')
  const nextRole = role(formData, 'role')
  if (!userId || !nextRole) return failed('That role is not one you can assign.')

  const api = await authenticatedApi()
  try {
    await api.updateMember(userId, { role: nextRole })
    revalidatePath(TEAM_PATH)
    return succeeded(`Role changed to ${nextRole}.`)
  } catch (error) {
    return fromError(error)
  }
}

export async function setMemberActiveAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const userId = text(formData, 'user_id')
  if (!userId) return failed('That member could not be identified.')
  const active = text(formData, 'is_active') === 'true'

  const api = await authenticatedApi()
  try {
    await api.updateMember(userId, { is_active: active })
    revalidatePath(TEAM_PATH)
    return succeeded(active ? 'Member reinstated.' : 'Member suspended.')
  } catch (error) {
    return fromError(error)
  }
}

export async function removeMemberAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const userId = text(formData, 'user_id')
  if (!userId) return failed('That member could not be identified.')

  const api = await authenticatedApi()
  try {
    await api.removeMember(userId)
    revalidatePath(TEAM_PATH)
    return succeeded('Member removed. The documents they uploaded are kept.')
  } catch (error) {
    return fromError(error)
  }
}

export async function revokeInvitationAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const invitationId = text(formData, 'invitation_id')
  if (!invitationId) return failed('That invitation could not be identified.')

  const api = await authenticatedApi()
  try {
    await api.revokeInvitation(invitationId)
    revalidatePath(TEAM_PATH)
    return succeeded('Invitation revoked. The link stops working immediately.')
  } catch (error) {
    return fromError(error)
  }
}
