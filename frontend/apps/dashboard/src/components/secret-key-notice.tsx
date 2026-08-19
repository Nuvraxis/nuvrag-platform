import { Alert, AlertDescription } from '@rag/ui'

import { CopyButton } from './copy-button'

/**
 * The API returns a chatbot's secret key exactly once, at creation or rotation. If it is
 * lost the only recovery is another rotation, so it gets its own prominent block rather
 * than a line in a table.
 */
export function SecretKeyNotice({ secretKey }: { secretKey: string }) {
  return (
    <Alert variant="warning" className="space-y-3">
      <AlertDescription>
        <p className="font-medium">Copy the secret key now — it is not shown again.</p>
        <div className="flex flex-wrap items-center gap-3">
          <code className="bg-card text-foreground min-w-0 flex-1 overflow-x-auto rounded-md px-3 py-2 font-mono text-xs">
            {secretKey}
          </code>
          <CopyButton value={secretKey} label="Copy key" />
        </div>
        <p className="text-xs">
          Used for server-to-server calls. The widget embeds the public key instead, which is safe
          to expose.
        </p>
      </AlertDescription>
    </Alert>
  )
}
