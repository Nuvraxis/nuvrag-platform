import type { CitedSource, MessageRole } from '@rag/api-client'
import { Badge, buttonVariants, Card, CardContent, CardHeader, CardTitle, Separator } from '@rag/ui'
import type { Metadata } from 'next'
import Link from 'next/link'
import { Suspense } from 'react'

import PageLoading from '@/components/page-loading'
import { PageHeader } from '@/components/page-header'
import { TicketControls } from '@/components/ticket-controls'
import { TicketPriorityBadge, TicketStatusBadge } from '@/components/status-badge'
import { TicketReplyForm } from '@/components/ticket-reply-form'
import { fetchApi } from '@/lib/api'
import { formatDateTime, formatDuration } from '@/lib/format'

export const metadata: Metadata = { title: 'Ticket' }

/** The API stores cited chunks alongside the answer, so no join is needed to render them. */
function sourcesOf(raw: Record<string, unknown>[] | null | undefined): CitedSource[] {
  return (raw ?? []) as unknown as CitedSource[]
}

const ROLE_LABEL: Record<MessageRole, string> = {
  user: 'visitor',
  assistant: 'assistant',
  staff: 'support',
}

async function TicketDetail({ params }: { params: Promise<{ ticketId: string }> }) {
  const { ticketId } = await params

  const [detail, team] = await Promise.all([
    fetchApi((api) => api.getTicket(ticketId)),
    fetchApi((api) => api.listMembers()),
  ])
  const { ticket, messages, memory } = detail

  const assignee = ticket.assigned_to
    ? team.members.find((member) => member.id === ticket.assigned_to)
    : undefined

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link href="/tickets" className={buttonVariants({ variant: 'secondary', size: 'sm' })}>
        Back to tickets
      </Link>

      <PageHeader
        title={ticket.subject ?? 'Ticket'}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <TicketStatusBadge status={ticket.status} />
            <TicketPriorityBadge priority={ticket.priority} />
            <span>opened {formatDateTime(ticket.created_at)}</span>
            {ticket.escalation_reason ? (
              <Badge variant="outline">{ticket.escalation_reason.replace(/_/g, ' ')}</Badge>
            ) : null}
          </span>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Visitor</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <span className="text-muted-foreground block text-xs">Email</span>
              {/* The address the visitor gave so a human could reach them. Reaching out is
                  manual — the same arrangement as invitation links. */}
              <a href={`mailto:${ticket.visitor_email}`} className="text-primary hover:underline">
                {ticket.visitor_email}
              </a>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs">Name</span>
              <span className="text-foreground">{ticket.visitor_name ?? 'Not given'}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs">Reached us via</span>
              <span className="text-foreground">{ticket.source.replace(/_/g, ' ')}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs">Currently with</span>
              <span className="text-foreground">
                {ticket.assigned_to
                  ? (assignee?.full_name ?? assignee?.email ?? 'a former member')
                  : 'Nobody yet'}
              </span>
            </div>
          </div>

          <Separator />

          <TicketControls ticket={ticket} members={team.members} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Conversation</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="space-y-3">
            {messages.map((message) => {
              const sources = sourcesOf(message.sources_json)
              const fromUser = message.role === 'user'
              const fromStaff = message.role === 'staff'

              return (
                <li key={message.id}>
                  <Card className={fromUser ? 'bg-muted' : undefined}>
                    <CardContent className="space-y-3">
                      <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                        <Badge variant={fromStaff ? 'success' : fromUser ? 'outline' : 'default'}>
                          {ROLE_LABEL[message.role]}
                        </Badge>
                        <time dateTime={message.created_at}>
                          {formatDateTime(message.created_at)}
                        </time>
                        {message.latency_ms != null ? (
                          <span>· answered in {formatDuration(message.latency_ms)}</span>
                        ) : null}
                      </div>

                      <p className="text-foreground text-sm whitespace-pre-wrap">
                        {message.content}
                      </p>

                      {sources.length > 0 ? (
                        <details className="border-border bg-muted rounded-md border px-3 py-2">
                          <summary className="text-muted-foreground cursor-pointer text-xs font-medium">
                            {sources.length} cited passage{sources.length === 1 ? '' : 's'}
                          </summary>
                          <ul className="mt-2 space-y-2">
                            {sources.map((source) => (
                              <li key={source.chunk_id} className="text-muted-foreground text-xs">
                                <span className="text-foreground font-medium">
                                  [{source.marker}]
                                </span>{' '}
                                <span className="tabular-nums">
                                  similarity {source.similarity.toFixed(3)}
                                </span>
                                <p className="mt-1 line-clamp-3">{source.excerpt}</p>
                              </li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                    </CardContent>
                  </Card>
                </li>
              )
            })}
          </ol>

          {messages.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              This ticket was opened without a message.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>What we remember about this visitor</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">
            Short notes taken from what this visitor said on earlier visits, and given to the
            assistant when they come back. Read-only here — how long they are kept is set per
            chatbot on its settings tab.
          </p>

          {memory.total === 0 ? (
            <p className="text-muted-foreground text-sm">
              Nothing yet. Notes are only taken for visitors who have asked for a human, and only
              once the chatbot has embedded something.
            </p>
          ) : (
            <>
              <ul className="space-y-2">
                {memory.notes.map((note) => (
                  <li key={note.id} className="border-border rounded-md border px-3 py-2 text-sm">
                    <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                      <Badge variant="outline">{note.memory_type}</Badge>
                      <span>learned {formatDateTime(note.created_at)}</span>
                      <span>· last used {formatDateTime(note.last_referenced_at)}</span>
                    </div>
                    <p className="text-foreground mt-1 whitespace-pre-wrap">{note.content}</p>
                  </li>
                ))}
              </ul>

              {memory.total > memory.notes.length ? (
                <p className="text-muted-foreground text-xs">
                  Showing the {memory.notes.length} most recent of {memory.total}.
                </p>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <TicketReplyForm ticketId={ticket.id} />
        </CardContent>
      </Card>
    </div>
  )
}

export default async function TicketPage({ params }: { params: Promise<{ ticketId: string }> }) {
  return (
    <Suspense fallback={<PageLoading />}>
      <TicketDetail params={params} />
    </Suspense>
  )
}
