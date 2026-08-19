import {
  Alert,
  AlertDescription,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@rag/ui'
import type { Metadata } from 'next'
import Link from 'next/link'

import { CopyButton } from '@/components/copy-button'
import { RotateSecretPanel } from '@/components/rotate-secret-panel'
import { fetchApi } from '@/lib/api'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

export const metadata: Metadata = { title: 'Embed' }

async function Embed({ params }: { params: Promise<{ chatbotId: string }> }) {
  const { chatbotId } = await params
  const [chatbot, snippet] = await Promise.all([
    fetchApi((api) => api.getChatbot(chatbotId)),
    fetchApi((api) => api.embedSnippet(chatbotId)),
  ])

  return (
    <div className="space-y-6">
      {/* Before the origins warning: a paused chatbot shows nothing whatever the allow-list
          says, so it is the more useful thing to read first. Without this, copying the
          snippet while paused ends in a correctly-pasted embed that renders nothing, with no
          indication anywhere of why. */}
      {chatbot.status !== 'active' ? (
        <Alert variant="warning">
          <AlertDescription>
            This chatbot is <strong>{chatbot.status}</strong>, so the widget does not appear on any
            site — the snippet below will render nothing until it is active again. Change it in{' '}
            <Link
              href={`/chatbots/${chatbotId}/settings`}
              className="font-medium underline underline-offset-4"
            >
              settings
            </Link>
            .
          </AlertDescription>
        </Alert>
      ) : null}

      {chatbot.allowed_origins.length === 0 ? (
        <Alert variant="warning">
          <AlertDescription>
            No origins are allowed yet, so the API will refuse every widget request. Add the sites
            this chatbot is embedded on in{' '}
            <Link
              href={`/chatbots/${chatbotId}/settings`}
              className="font-medium underline underline-offset-4"
            >
              settings
            </Link>
            .
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <div className="space-y-1">
            <CardTitle>Embed snippet</CardTitle>
            <CardDescription>
              Paste this once into the page template. The loader injects the chat UI in an iframe,
              so nothing on the host page can be affected by it.
            </CardDescription>
          </div>
          <CopyButton value={snippet.snippet} label="Copy snippet" />
        </CardHeader>
        <CardContent>
          <pre className="bg-muted overflow-x-auto rounded-md p-4 text-xs">
            <code className="font-mono">{snippet.snippet}</code>
          </pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="space-y-1">
            <CardTitle>Keys and origins</CardTitle>
            <CardDescription>
              The public key identifies the chatbot and is meant to be visible in page source. What
              actually authorises a request is the site the widget is running on being on the list
              below, which the browser reports and a page cannot fake.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <dt className="text-muted-foreground w-28 shrink-0">Public key</dt>
              <dd className="min-w-0 flex-1 overflow-x-auto font-mono text-xs">
                {snippet.public_key}
              </dd>
              <CopyButton value={snippet.public_key} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <dt className="text-muted-foreground w-28 shrink-0">Loader</dt>
              <dd className="min-w-0 flex-1 overflow-x-auto font-mono text-xs">
                {snippet.loader_url}
              </dd>
            </div>
            <div className="flex flex-wrap gap-2">
              <dt className="text-muted-foreground w-28 shrink-0">Allowed origins</dt>
              <dd className="min-w-0 flex-1">
                {chatbot.allowed_origins.length === 0 ? (
                  <span className="text-muted-foreground">None</span>
                ) : (
                  <ul className="space-y-1 font-mono text-xs">
                    {chatbot.allowed_origins.map((origin) => (
                      <li key={origin}>{origin}</li>
                    ))}
                  </ul>
                )}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <RotateSecretPanel chatbotId={chatbotId} />
    </div>
  )
}

export default async function EmbedPage({ params }: { params: Promise<{ chatbotId: string }> }) {
  return (
    <Suspense fallback={<PageLoading />}>
      <Embed params={params} />
    </Suspense>
  )
}
