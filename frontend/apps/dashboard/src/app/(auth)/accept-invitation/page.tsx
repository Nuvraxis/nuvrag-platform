import { type InvitationPreview, isApiError } from '@rag/api-client'
import { Alert, AlertDescription, buttonVariants, Card, CardContent } from '@rag/ui'
import type { Metadata } from 'next'
import Link from 'next/link'

import { AcceptInvitationForm } from '@/components/accept-invitation-form'
import { publicApi } from '@/lib/api'

export const metadata: Metadata = { title: 'Join a team' }

/**
 * Unauthenticated on purpose: the visitor has no account yet, and the token is the only
 * credential in play. A spent, revoked, expired or invented token all come back the same
 * way, so a stranger with a random string learns nothing from the difference.
 */
async function loadPreview(token: string): Promise<InvitationPreview | null> {
  try {
    return await publicApi().previewInvitation(token)
  } catch (error) {
    if (isApiError(error) && error.isNotFound) {
      return null
    }
    throw error
  }
}

function Unusable({ reason }: { reason: string }) {
  return (
    <Card>
      <CardContent className="space-y-4">
        <Alert variant="destructive">
          <AlertDescription>{reason}</AlertDescription>
        </Alert>
        <p className="text-muted-foreground text-sm">
          Ask whoever invited you to send a fresh link — invitations expire, and revoked ones stop
          working straight away.
        </p>
        <Link href="/login" className={buttonVariants({ variant: 'secondary' })}>
          Back to sign in
        </Link>
      </CardContent>
    </Card>
  )
}

export default async function AcceptInvitationPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>
}) {
  const { token } = await searchParams
  if (!token) {
    return <Unusable reason="This link is missing its invitation token." />
  }

  const preview = await loadPreview(token)
  if (!preview) {
    return <Unusable reason="This invitation is no longer valid." />
  }

  return <AcceptInvitationForm token={token} preview={preview} />
}
