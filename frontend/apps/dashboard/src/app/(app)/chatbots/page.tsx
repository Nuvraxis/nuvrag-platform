import { buttonVariants, Card, EmptyState } from '@rag/ui'
import type { Metadata } from 'next'
import Link from 'next/link'

import { PageHeader } from '@/components/page-header'
import { ChatbotStatusBadge } from '@/components/status-badge'
import { fetchApi } from '@/lib/api'
import { formatRelative } from '@/lib/format'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

export const metadata: Metadata = { title: 'Chatbots' }

async function Chatbots() {
  const page = await fetchApi((api) => api.listChatbots({ limit: 100 }))

  return (
    <>
      <PageHeader
        title="Chatbots"
        description={`${page.total} chatbot${page.total === 1 ? '' : 's'} in this organisation`}
        actions={
          <Link href="/chatbots/new" className={buttonVariants()}>
            New chatbot
          </Link>
        }
      />

      {page.items.length === 0 ? (
        <EmptyState
          title="No chatbots yet"
          description="Create one, upload the documents it should answer from, then drop the embed snippet on your site."
          action={
            <Link
              href="/chatbots/new"
              className="text-primary font-medium underline-offset-4 hover:underline"
            >
              Create your first chatbot
            </Link>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {page.items.map((chatbot) => (
            <li key={chatbot.id}>
              <Link href={`/chatbots/${chatbot.id}`} className="block h-full">
                <Card className="hover:border-primary h-full transition-colors">
                  <div className="space-y-3 px-5 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <h2 className="text-foreground font-medium">{chatbot.name}</h2>
                      <ChatbotStatusBadge status={chatbot.status} />
                    </div>
                    <p className="text-muted-foreground line-clamp-2 min-h-10 text-sm">
                      {chatbot.description ?? 'No description.'}
                    </p>
                    <dl className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
                      <div className="flex gap-1">
                        <dt>Slug</dt>
                        <dd className="text-foreground font-mono">{chatbot.slug}</dd>
                      </div>
                      <div className="flex gap-1">
                        <dt>Origins</dt>
                        <dd className="text-foreground">{chatbot.allowed_origins.length}</dd>
                      </div>
                      <div className="flex gap-1">
                        <dt>Updated</dt>
                        <dd className="text-foreground">{formatRelative(chatbot.updated_at)}</dd>
                      </div>
                    </dl>
                  </div>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

export default async function ChatbotsPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <Chatbots />
    </Suspense>
  )
}
