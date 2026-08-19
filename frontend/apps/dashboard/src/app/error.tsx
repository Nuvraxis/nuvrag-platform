'use client'

import { Alert, AlertDescription, Button, Card, CardContent } from '@rag/ui'
import { useEffect } from 'react'

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // The message is scrubbed before it reaches the browser; the digest is what ties this
    // back to the full stack trace in the server logs.
    console.error('dashboard.render_failed', error.digest ?? error.message)
  }, [error])

  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center px-6">
      <Card>
        <CardContent className="space-y-4">
          <h1 className="text-foreground text-lg font-semibold">Something went wrong</h1>
          <Alert variant="destructive">
            <AlertDescription>
              The dashboard could not load this page. If it keeps happening, check that the API is
              reachable.
            </AlertDescription>
          </Alert>
          {error.digest ? (
            <p className="text-muted-foreground text-xs">
              Reference <code className="font-mono">{error.digest}</code>
            </p>
          ) : null}
          <Button onClick={reset}>Try again</Button>
        </CardContent>
      </Card>
    </main>
  )
}
