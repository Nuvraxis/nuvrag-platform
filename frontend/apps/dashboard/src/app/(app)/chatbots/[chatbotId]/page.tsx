import {
  Alert,
  AlertDescription,
  buttonVariants,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Stat,
} from '@rag/ui'
import Link from 'next/link'

import { ActivityChart } from '@/components/activity-chart'
import { isAIConfigReady, loadAIConfig } from '@/lib/ai-config'
import { fetchApi } from '@/lib/api'
import { formatDuration, formatNumber } from '@/lib/format'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

const WINDOW_DAYS = 30

async function ChatbotOverview({ params }: { params: Promise<{ chatbotId: string }> }) {
  const { chatbotId } = await params
  const [analytics, aiConfig] = await Promise.all([
    fetchApi((api) => api.analytics(chatbotId, { days: WINDOW_DAYS })),
    loadAIConfig(chatbotId),
  ])
  const { documents, messages } = analytics

  const aiReady = isAIConfigReady(aiConfig)
  // Without a provider nothing else on this page is actionable: uploads are refused and
  // questions cannot be answered, so this comes before the document warning rather than
  // alongside it.
  const answeringIsPossible = documents.ready > 0

  return (
    <div className="space-y-6">
      {aiReady ? null : (
        <Alert variant="destructive">
          <AlertDescription>
            {aiConfig
              ? 'This chatbot’s AI provider is missing some of its connection details, so uploads and answers are both refused.'
              : 'No AI provider is configured, so this chatbot cannot ingest documents or answer questions yet.'}{' '}
            <Link
              href={`/chatbots/${chatbotId}/ai`}
              className="font-medium underline underline-offset-4"
            >
              {aiConfig ? 'Finish setting it up' : 'Choose one'}
            </Link>
            .
          </AlertDescription>
        </Alert>
      )}

      {answeringIsPossible || !aiReady ? null : (
        <Alert variant="warning">
          <AlertDescription>
            No documents have finished ingesting, so this chatbot has nothing to answer from and
            will decline every question.{' '}
            <Link
              href={`/chatbots/${chatbotId}/documents`}
              className="font-medium underline underline-offset-4"
            >
              Upload one
            </Link>
            .
          </AlertDescription>
        </Alert>
      )}

      {documents.failed > 0 ? (
        <Alert variant="destructive">
          <AlertDescription>
            {documents.failed} document{documents.failed === 1 ? '' : 's'} failed to ingest.{' '}
            <Link
              href={`/chatbots/${chatbotId}/documents`}
              className="font-medium underline underline-offset-4"
            >
              Review and reprocess
            </Link>
            .
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Documents ready"
          value={formatNumber(documents.ready)}
          hint={`${formatNumber(documents.total)} uploaded in total`}
        />
        <Stat
          label="Indexed passages"
          value={formatNumber(documents.chunks)}
          hint="Embedded chunks available for retrieval"
        />
        <Stat
          label="Conversations"
          value={formatNumber(analytics.conversations)}
          hint={`${formatNumber(messages.total)} messages exchanged`}
        />
        <Stat
          label="Average answer time"
          value={formatDuration(messages.average_latency_ms)}
          hint="Retrieval plus generation, measured server-side"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Last {WINDOW_DAYS} days</CardTitle>
        </CardHeader>
        <CardContent>
          {analytics.conversations === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              Nothing yet — activity appears here once the widget is live.
            </p>
          ) : (
            <ActivityChart points={analytics.daily} />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Ingestion</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              {(
                [
                  ['Ready', documents.ready],
                  ['Processing', documents.processing],
                  ['Pending', documents.pending],
                  ['Failed', documents.failed],
                ] as const
              ).map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="text-foreground font-medium tabular-nums">
                    {formatNumber(value)}
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Next steps</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Link
              href={`/chatbots/${chatbotId}/documents`}
              className={buttonVariants({ variant: 'secondary', size: 'sm' })}
            >
              Manage documents
            </Link>
            <Link
              href={`/chatbots/${chatbotId}/embed`}
              className={buttonVariants({ variant: 'secondary', size: 'sm' })}
            >
              Get the embed snippet
            </Link>
            <Link
              href={`/chatbots/${chatbotId}/ai`}
              className={buttonVariants({ variant: 'secondary', size: 'sm' })}
            >
              {aiReady ? 'Change AI provider' : 'Choose an AI provider'}
            </Link>
            <Link
              href={`/chatbots/${chatbotId}/settings`}
              className={buttonVariants({ variant: 'secondary', size: 'sm' })}
            >
              Tune retrieval
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default async function ChatbotOverviewPage({
  params,
}: {
  params: Promise<{ chatbotId: string }>
}) {
  return (
    <Suspense fallback={<PageLoading />}>
      <ChatbotOverview params={params} />
    </Suspense>
  )
}
