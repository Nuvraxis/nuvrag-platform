import type { CitedSource } from '@rag/api-client'
import { Badge, buttonVariants, Card, CardContent } from '@rag/ui'
import type { Metadata } from 'next'
import Link from 'next/link'

import { ActionForm } from '@/components/action-form'
import { ConfirmSubmit } from '@/components/confirm-submit'
import { fetchApi } from '@/lib/api'
import { deleteConversationAction } from '@/lib/actions/conversations'
import { formatDateTime, formatDuration } from '@/lib/format'

export const metadata: Metadata = { title: 'Transcript' }

/** The API stores cited chunks alongside the answer, so no join is needed to render them. */
function sourcesOf(raw: Record<string, unknown>[] | null | undefined): CitedSource[] {
  return (raw ?? []) as unknown as CitedSource[]
}

export default async function TranscriptPage({
  params,
}: {
  params: Promise<{ chatbotId: string; conversationId: string }>
}) {
  const { chatbotId, conversationId } = await params
  const page = await fetchApi((api) => api.listMessages(chatbotId, conversationId, { limit: 200 }))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href={`/chatbots/${chatbotId}/conversations`}
          className={buttonVariants({ variant: 'secondary', size: 'sm' })}
        >
          Back to conversations
        </Link>

        {/* How a single erasure request is honoured, rather than waiting for the retention
            sweep — which may not be switched on at all. */}
        <ActionForm action={deleteConversationAction} announceSuccess={false}>
          <input type="hidden" name="chatbot_id" value={chatbotId} />
          <input type="hidden" name="conversation_id" value={conversationId} />
          <ConfirmSubmit
            variant="destructive"
            size="sm"
            confirmTitle="Delete this conversation?"
            confirmDescription="The transcript, any support ticket raised from it, and everything remembered about this visitor are removed. This cannot be undone."
            confirmLabel="Delete conversation"
            pendingLabel="Deleting…"
          >
            Delete conversation
          </ConfirmSubmit>
        </ActionForm>
      </div>

      <ol className="space-y-3">
        {page.items.map((message) => {
          const sources = sourcesOf(message.sources_json)
          const fromUser = message.role === 'user'

          return (
            <li key={message.id}>
              <Card className={fromUser ? 'bg-muted' : undefined}>
                <CardContent className="space-y-3 overflow-y-auto">
                  <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant={fromUser ? 'outline' : 'default'}>{message.role}</Badge>
                    <time dateTime={message.created_at}>{formatDateTime(message.created_at)}</time>
                    {message.latency_ms != null ? (
                      <span>· answered in {formatDuration(message.latency_ms)}</span>
                    ) : null}
                  </div>

                  <p className="text-foreground text-sm whitespace-pre-wrap">{message.content}</p>

                  {sources.length > 0 ? (
                    <details className="border-border bg-muted rounded-md border px-3 py-2">
                      <summary className="text-muted-foreground cursor-pointer text-xs font-medium">
                        {sources.length} cited passage{sources.length === 1 ? '' : 's'}
                      </summary>
                      <ul className="mt-2 space-y-2">
                        {sources.map((source) => (
                          <li key={source.chunk_id} className="text-muted-foreground text-xs">
                            <span className="text-foreground font-medium">[{source.marker}]</span>{' '}
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

      {page.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">This conversation has no messages.</p>
      ) : null}
    </div>
  )
}
