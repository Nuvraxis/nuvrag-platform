import {
  Card,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHead,
  TableRow,
} from '@rag/ui'
import type { Metadata } from 'next'
import Link from 'next/link'

import { fetchApi } from '@/lib/api'
import { formatNumber, formatRelative } from '@/lib/format'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

export const metadata: Metadata = { title: 'Conversations' }

async function Conversations({ params }: { params: Promise<{ chatbotId: string }> }) {
  const { chatbotId } = await params
  const page = await fetchApi((api) => api.listConversations(chatbotId, { limit: 100 }))

  if (page.items.length === 0) {
    return (
      <EmptyState
        title="No conversations yet"
        description="Every widget session becomes a conversation here, identified by an anonymous session id — no personal data is collected from end users."
      />
    )
  }

  return (
    <Card>
      <>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Session</TableHead>
              <TableHead>Opening question</TableHead>
              <TableHead className="text-right">Messages</TableHead>
              <TableHead>Last activity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.items.map((conversation) => (
              <TableRow key={conversation.id} className="hover:bg-muted">
                <TableCell className="font-mono text-xs">
                  <Link
                    href={`/chatbots/${chatbotId}/conversations/${conversation.id}`}
                    className="text-primary hover:underline"
                  >
                    {conversation.external_session_id.slice(0, 16)}
                  </Link>
                </TableCell>
                <TableCell className="max-w-md truncate text-sm">
                  {conversation.title ?? '—'}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {formatNumber(conversation.message_count)}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {formatRelative(conversation.updated_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </>
    </Card>
  )
}

export default async function ConversationsPage({
  params,
}: {
  params: Promise<{ chatbotId: string }>
}) {
  return (
    <Suspense fallback={<PageLoading />}>
      <Conversations params={params} />
    </Suspense>
  )
}
