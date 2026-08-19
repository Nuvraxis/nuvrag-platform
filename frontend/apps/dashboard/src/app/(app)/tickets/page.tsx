import type { TicketStatus } from '@rag/api-client'
import { TICKET_STATUSES } from '@rag/types'
import {
  Card,
  CardContent,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@rag/ui'
import type { Metadata } from 'next'
import Link from 'next/link'
import { Suspense } from 'react'

import PageLoading from '@/components/page-loading'
import { PageHeader } from '@/components/page-header'
import { TicketFilters } from '@/components/ticket-filters'
import { TicketPriorityBadge, TicketStatusBadge } from '@/components/status-badge'
import { fetchApi } from '@/lib/api'
import { formatRelative } from '@/lib/format'

export const metadata: Metadata = { title: 'Tickets' }

type Search = { chatbot_id?: string; status?: string }

function asStatus(value: string | undefined): TicketStatus | undefined {
  return (TICKET_STATUSES as readonly string[]).includes(value ?? '')
    ? (value as TicketStatus)
    : undefined
}

async function Tickets({ searchParams }: { searchParams: Promise<Search> }) {
  const filters = await searchParams
  const status = asStatus(filters.status)
  const chatbotId = filters.chatbot_id || undefined

  const [page, chatbots, team] = await Promise.all([
    fetchApi((api) => api.listTickets({ limit: 100, status, chatbot_id: chatbotId })),
    fetchApi((api) => api.listChatbots({ limit: 100 })),
    fetchApi((api) => api.listMembers()),
  ])

  // Assignment is stored as a user id; the queue reads better with a name against it.
  const nameFor = new Map(team.members.map((m) => [m.id, m.full_name ?? m.email]))
  const chatbotName = new Map(chatbots.items.map((c) => [c.id, c.name]))

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Tickets"
        description="Conversations a visitor asked a human to pick up. Replies reach them the next time they open the widget — nothing is emailed."
      />

      <TicketFilters chatbots={chatbots.items} status={status} chatbotId={chatbotId} />

      {page.items.length === 0 ? (
        <EmptyState
          title="Nothing in the queue"
          description="A ticket appears here when a visitor asks to talk to a human, or takes the offer after the assistant cannot answer from your documents."
        />
      ) : (
        <Card>
          <CardContent className="overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Visitor</TableHead>
                  <TableHead>Subject</TableHead>
                  <TableHead>Chatbot</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead>Assigned</TableHead>
                  <TableHead>Opened</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {page.items.map((ticket) => (
                  <TableRow key={ticket.id} className="hover:bg-muted">
                    <TableCell>
                      <Link
                        href={`/tickets/${ticket.id}`}
                        className="text-primary font-medium hover:underline"
                      >
                        {ticket.visitor_name ?? ticket.visitor_email}
                      </Link>
                      {ticket.visitor_name ? (
                        <span className="text-muted-foreground block text-xs">
                          {ticket.visitor_email}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-sm">
                      {ticket.subject ?? '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {chatbotName.get(ticket.chatbot_id) ?? '—'}
                    </TableCell>
                    <TableCell>
                      <TicketStatusBadge status={ticket.status} />
                    </TableCell>
                    <TableCell>
                      <TicketPriorityBadge priority={ticket.priority} />
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {ticket.assigned_to
                        ? (nameFor.get(ticket.assigned_to) ?? 'a former member')
                        : '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatRelative(ticket.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default async function TicketsPage({ searchParams }: { searchParams: Promise<Search> }) {
  return (
    <Suspense fallback={<PageLoading />}>
      <Tickets searchParams={searchParams} />
    </Suspense>
  )
}
