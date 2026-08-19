import {
  Card,
  EmptyState,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHead,
  TableRow,
  CardContent,
} from '@rag/ui'
import type { Metadata } from 'next'

import { ActionForm } from '@/components/action-form'
import { ConfirmSubmit } from '@/components/confirm-submit'
import { DocumentUploader } from '@/components/document-uploader'
import { IngestionPoller } from '@/components/ingestion-poller'
import { SubmitButton } from '@/components/submit-button'
import { DocumentStatusBadge } from '@/components/status-badge'
import { fetchApi } from '@/lib/api'
import { deleteDocumentAction, reprocessDocumentAction } from '@/lib/actions/documents'
import { formatBytes, formatNumber, formatRelative } from '@/lib/format'
import PageLoading from '@/components/page-loading'
import { Suspense } from 'react'

export const metadata: Metadata = { title: 'Documents' }

const IN_FLIGHT = new Set(['pending', 'processing'])

async function Documents({ params }: { params: Promise<{ chatbotId: string }> }) {
  const { chatbotId } = await params
  const page = await fetchApi((api) => api.listDocuments(chatbotId, { limit: 100 }))
  const stillIngesting = page.items.some((document) => IN_FLIGHT.has(document.status))

  return (
    <div className="space-y-6">
      <IngestionPoller active={stillIngesting} />
      <DocumentUploader chatbotId={chatbotId} />

      {page.items.length === 0 ? (
        <EmptyState
          title="No documents yet"
          description="Uploads are queued to the ingestion worker, which extracts the text, splits it into passages and embeds them."
        />
      ) : (
        <Card>
          <CardContent className="overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>File</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Passages</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead>
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {page.items.map((document) => (
                  <TableRow key={document.id}>
                    <TableCell>
                      <span className="block font-medium">{document.filename}</span>
                      <span className="text-muted-foreground text-xs">
                        {document.file_type.toUpperCase()} · {formatBytes(document.size_bytes)}
                      </span>
                    </TableCell>
                    <TableCell>
                      <DocumentStatusBadge status={document.status} />
                      {document.error_message ? (
                        <p className="text-destructive mt-1 max-w-xs text-xs">
                          {document.error_message}
                        </p>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatNumber(document.chunk_count)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {formatRelative(document.created_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-2">
                        <ActionForm action={reprocessDocumentAction}>
                          <input type="hidden" name="chatbot_id" value={chatbotId} />
                          <input type="hidden" name="document_id" value={document.id} />
                          <SubmitButton
                            variant="secondary"
                            size="sm"
                            disabled={IN_FLIGHT.has(document.status)}
                          >
                            Reprocess
                          </SubmitButton>
                        </ActionForm>
                        <ActionForm action={deleteDocumentAction}>
                          <input type="hidden" name="chatbot_id" value={chatbotId} />
                          <input type="hidden" name="document_id" value={document.id} />
                          <ConfirmSubmit
                            variant="ghost"
                            size="sm"
                            confirmTitle={`Delete ${document.filename}?`}
                            confirmDescription="Its indexed passages go with it, so the chatbot stops answering from this document."
                          >
                            Delete
                          </ConfirmSubmit>
                        </ActionForm>
                      </div>
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

export default async function DocumentsPage({
  params,
}: {
  params: Promise<{ chatbotId: string }>
}) {
  return (
    <Suspense fallback={<PageLoading />}>
      <Documents params={params} />
    </Suspense>
  )
}
