import type { UserRole } from '@rag/api-client'
import { USER_ROLES } from '@rag/types'
import {
  Badge,
  Card,
  CardHeader,
  CardTitle,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHead,
  TableRow,
  CardContent,
} from '@rag/ui'
import type { Metadata } from 'next'

import { ActionForm } from '@/components/action-form'
import { ConfirmSubmit } from '@/components/confirm-submit'
import { InviteMemberForm } from '@/components/invite-member-form'
import { MemberRowActions } from '@/components/member-row-actions'
import { PageHeader } from '@/components/page-header'
import { revokeInvitationAction } from '@/lib/actions/team'
import { fetchApi } from '@/lib/api'
import { formatDateTime, formatRelative } from '@/lib/format'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

export const metadata: Metadata = { title: 'Team' }

const RANK: Record<UserRole, number> = { member: 0, admin: 1, owner: 2 }

/** Nobody may hand out more authority than they hold; the API rejects it either way. */
function assignableRoles(actorRole: UserRole): UserRole[] {
  return USER_ROLES.filter((role) => RANK[role] <= RANK[actorRole])
}

async function Team() {
  const viewer = await fetchApi((api) => api.me())
  const canManage = RANK[viewer.role] >= RANK.admin

  const [team, invitations] = await Promise.all([
    fetchApi((api) => api.listMembers()),
    canManage ? fetchApi((api) => api.listInvitations({ status: 'pending' })) : Promise.resolve([]),
  ])

  const roles = assignableRoles(viewer.role)

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        title="Team"
        description="Everyone here shares this organisation's chatbots, documents and conversations."
      />

      <Card>
        <CardHeader>
          <CardTitle>
            Members{' '}
            <span className="text-muted-foreground font-normal">({team.members.length})</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Person</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead className="text-right">
                  {canManage ? 'Manage' : <span className="sr-only">Manage</span>}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {team.members.map((member) => (
                <TableRow key={member.id}>
                  <TableCell>
                    <span className="block font-medium">{member.full_name ?? member.email}</span>
                    <span className="text-muted-foreground text-xs">{member.email}</span>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={member.role === 'owner' ? 'default' : 'outline'}>
                        {member.role}
                      </Badge>
                      {member.is_active ? null : <Badge variant="warning">suspended</Badge>}
                      {member.id === viewer.id ? (
                        <span className="text-muted-foreground text-xs">you</span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">
                    {formatRelative(member.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {canManage ? (
                      <MemberRowActions
                        member={member}
                        assignableRoles={roles}
                        editable={member.id !== viewer.id && RANK[member.role] <= RANK[viewer.role]}
                      />
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {canManage ? (
        <>
          <InviteMemberForm assignableRoles={roles} />

          <Card>
            <CardHeader>
              <CardTitle>Pending invitations</CardTitle>
            </CardHeader>
            {invitations.length === 0 ? (
              <EmptyState
                className="m-5 border-0"
                title="Nothing outstanding"
                description="Invitations appear here until they are accepted, revoked or expire."
              />
            ) : (
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Email</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Expires</TableHead>
                      <TableHead>
                        <span className="sr-only">Revoke</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {invitations.map((invitation) => (
                      <TableRow key={invitation.id}>
                        <TableCell className="font-medium">{invitation.email}</TableCell>
                        <TableCell>
                          <Badge>{invitation.role}</Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {formatDateTime(invitation.expires_at)}
                        </TableCell>
                        <TableCell className="text-right">
                          <ActionForm action={revokeInvitationAction}>
                            <input type="hidden" name="invitation_id" value={invitation.id} />
                            <ConfirmSubmit
                              variant="ghost"
                              size="sm"
                              confirmTitle={`Revoke the invitation for ${invitation.email}?`}
                              confirmDescription="Their link stops working immediately. Inviting them again issues a new one."
                            >
                              Revoke
                            </ConfirmSubmit>
                          </ActionForm>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            )}
          </Card>
        </>
      ) : null}
    </div>
  )
}

export default async function TeamPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <Team />
    </Suspense>
  )
}
