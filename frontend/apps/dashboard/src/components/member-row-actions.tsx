'use client'

import type { User, UserRole } from '@rag/api-client'
import { NativeSelect } from '@rag/ui'
import { useRef } from 'react'

import {
  removeMemberAction,
  setMemberActiveAction,
  updateMemberRoleAction,
} from '@/lib/actions/team'

import { ActionForm } from './action-form'
import { ConfirmSubmit } from './confirm-submit'
import { SubmitButton } from './submit-button'

export interface MemberRowActionsProps {
  member: User
  /** Roles the signed-in user is allowed to assign — never above their own. */
  assignableRoles: readonly UserRole[]
  /** False for your own row and for anyone above you; the API enforces the same rules. */
  editable: boolean
}

export function MemberRowActions({ member, assignableRoles, editable }: MemberRowActionsProps) {
  const roleFormRef = useRef<HTMLFormElement>(null)

  if (!editable) {
    return <span className="text-muted-foreground text-xs">—</span>
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <ActionForm
        formRef={roleFormRef}
        action={updateMemberRoleAction}
        className="flex items-center gap-2"
      >
        <input type="hidden" name="user_id" value={member.id} />
        <NativeSelect
          name="role"
          defaultValue={member.role}
          aria-label={`Role for ${member.email}`}
          className="h-8 w-32 py-1 text-xs"
          // Submitting on change keeps the row to one control instead of a select plus a
          // save button that is meaningless until the select moves.
          onChange={() => roleFormRef.current?.requestSubmit()}
        >
          {assignableRoles.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </NativeSelect>
      </ActionForm>

      <ActionForm action={setMemberActiveAction}>
        <input type="hidden" name="user_id" value={member.id} />
        <input type="hidden" name="is_active" value={member.is_active ? 'false' : 'true'} />
        <SubmitButton variant="secondary" size="sm">
          {member.is_active ? 'Suspend' : 'Reinstate'}
        </SubmitButton>
      </ActionForm>

      <ActionForm action={removeMemberAction}>
        <input type="hidden" name="user_id" value={member.id} />
        <ConfirmSubmit
          variant="ghost"
          size="sm"
          confirmTitle={`Remove ${member.email} from the organisation?`}
          confirmDescription="They lose access straight away. Documents they uploaded are kept."
        >
          Remove
        </ConfirmSubmit>
      </ActionForm>
    </div>
  )
}
