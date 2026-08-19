'use client'

import { UPLOAD_EXTENSIONS } from '@rag/types'
import {
  Alert,
  AlertDescription,
  Button,
  Card,
  CardContent,
  Field,
  FieldDescription,
  FieldLabel,
  FieldGroup,
  Input,
  Spinner,
  cn,
  toast,
} from '@rag/ui'
import { CircleAlert, CircleCheck, Trash2, Upload } from 'lucide-react'
import {
  type ChangeEvent,
  type DragEvent,
  type SubmitEvent,
  useActionState,
  useRef,
  useState,
} from 'react'

import { uploadDocumentAction } from '@/lib/actions/documents'
import { idle } from '@/lib/action-state'
import { formatBytes } from '@/lib/format'
import { SUPPORTED_FORMATS, rejectionReason } from '@/lib/uploads'

const ACCEPT = `${UPLOAD_EXTENSIONS.join(',')},application/pdf,text/markdown,text/plain`

type Stage = 'queued' | 'uploading' | 'done' | 'failed'

interface Queued {
  /** A counter rather than `crypto.randomUUID`, which needs a secure context. */
  id: number
  file: File
  stage: Stage
  /** Why it was refused, once it has been. */
  message?: string
}

/**
 * Queue several documents at once, by picking them or dropping them.
 *
 * Deliberately not built on `useActionForm` like the rest of the dashboard's forms: that
 * anatomy carries one result and one error per field, and this needs one of each per file.
 * The `<form action>` underneath is still real, so a browser with scripts disabled posts the
 * whole selection in one request and the action's loop handles it — see the note there.
 *
 * Files are uploaded one at a time on purpose. Next.js dispatches Server Actions sequentially
 * per client, so `Promise.all` here would buy nothing but a misleading progress display, and
 * one file per request keeps every body inside `serverActions.bodySizeLimit`.
 */
export function DocumentUploader({ chatbotId }: { chatbotId: string }) {
  // Only ever reached with scripts disabled, where `onSubmit` cannot cancel the submission —
  // which is also the only case where the banner below it is visible.
  const [state, formAction] = useActionState(uploadDocumentAction, idle)
  const [queue, setQueue] = useState<Queued[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const nextId = useRef(0)
  // `dragenter` and `dragleave` also fire crossing every child, so the highlight follows a
  // depth count rather than the last event to arrive.
  const depth = useRef(0)

  const pending = queue.filter((item) => item.stage === 'queued')

  function enqueue(files: FileList | null): void {
    if (!files?.length) return

    setQueue((current) => {
      const seen = new Set(current.map(identity))
      const additions: Queued[] = []

      for (const file of files) {
        // Dropping the same file twice is an easy slip and would ingest it twice.
        if (seen.has(identity({ file }))) continue
        seen.add(identity({ file }))

        const reason = rejectionReason(file)
        additions.push({
          id: nextId.current++,
          file,
          stage: reason ? 'failed' : 'queued',
          message: reason ?? undefined,
        })
      }

      return [...current, ...additions]
    })
  }

  function onPicked(event: ChangeEvent<HTMLInputElement>): void {
    enqueue(event.target.files)
    // The queue below is the only place files are counted from here on; leaving the picker
    // holding a selection would show a second, staler answer beside it.
    event.target.value = ''
  }

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    depth.current = 0
    setDragging(false)
    enqueue(event.dataTransfer.files)
  }

  function onDragEnter(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    depth.current += 1
    setDragging(true)
  }

  function onDragLeave(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    depth.current = Math.max(0, depth.current - 1)
    if (depth.current === 0) setDragging(false)
  }

  function update(id: number, changes: Partial<Queued>): void {
    setQueue((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)))
  }

  async function upload(event: SubmitEvent<HTMLFormElement>): Promise<void> {
    // Scripts are running, so the queue takes over from the form's own submission.
    event.preventDefault()
    if (uploading) return
    if (pending.length === 0) {
      // The button cannot simply be disabled instead: without scripts the queue is always
      // empty, and disabling on that would leave the only upload button permanently dead.
      toast.error('Choose a file to upload.')
      return
    }

    setUploading(true)
    let queuedCount = 0
    let failedCount = 0

    for (const item of pending) {
      update(item.id, { stage: 'uploading', message: undefined })

      const data = new FormData()
      data.set('chatbot_id', chatbotId)
      data.set('file', item.file, item.file.name)

      const result = await uploadDocumentAction(idle, data)
      const ok = result.status === 'success'
      if (ok) queuedCount += 1
      else failedCount += 1

      update(item.id, {
        stage: ok ? 'done' : 'failed',
        message: ok ? undefined : (result.message ?? 'Upload failed.'),
      })
    }

    setUploading(false)

    // One summary rather than a toast per file: the rows already say which was which, and a
    // twenty-file batch would otherwise bury the page.
    if (failedCount === 0) {
      toast.success(
        queuedCount === 1 ? 'Queued for ingestion.' : `${queuedCount} files queued for ingestion.`,
      )
    } else if (queuedCount === 0) {
      toast.error(
        failedCount === 1
          ? 'That file could not be uploaded.'
          : `${failedCount} files could not be uploaded.`,
      )
    } else {
      toast.error(`${queuedCount} queued, ${failedCount} could not be uploaded.`)
    }
  }

  return (
    <Card>
      <CardContent>
        {/*
         * `action` stays on the element so a browser without scripts still posts the whole
         * selection to the Server Action; `onSubmit` cancels that for everyone else.
         *
         * `noValidate` because the picker is emptied as soon as its files join the queue, so a
         * `required` file input would be empty at submit time and the browser would refuse to
         * submit — taking `onSubmit` with it, and leaving a dead button. What is queued is
         * checked per file instead, and the action checks again for anyone posting directly.
         */}
        <form action={formAction} onSubmit={upload} noValidate>
          <input type="hidden" name="chatbot_id" value={chatbotId} />

          <FieldGroup className="gap-4">
            {state.message ? (
              <Alert
                variant={state.status === 'error' ? 'destructive' : 'default'}
                role="status"
                className="no-js-only"
              >
                <AlertDescription>{state.message}</AlertDescription>
              </Alert>
            ) : null}

            <Field>
              <FieldLabel htmlFor="documents">Add documents</FieldLabel>
              <div
                onDragEnter={onDragEnter}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
                className={cn(
                  'rounded-lg border border-dashed p-4 transition-colors',
                  dragging ? 'border-primary bg-accent/40' : 'border-input',
                )}
              >
                <Input
                  id="documents"
                  name="file"
                  type="file"
                  multiple
                  accept={ACCEPT}
                  onChange={onPicked}
                  className="file:bg-accent file:text-primary file:mr-3 file:rounded-md file:border-0 file:px-3 file:py-1 file:text-sm"
                />
                {/*
                 * Only true where the drop handlers can run, so it is hidden by the same
                 * `scripting` media query that reveals the no-JS banners.
                 */}
                <p className="text-muted-foreground js-only mt-2 text-sm">
                  …or drag files anywhere onto this panel. Several at a time is fine.
                </p>
              </div>
              <FieldDescription>{SUPPORTED_FORMATS} — up to 25 MB each.</FieldDescription>
            </Field>

            {queue.length > 0 ? (
              <ul className="divide-border divide-y rounded-lg border">
                {queue.map((item) => (
                  <li key={item.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                    <StageIcon stage={item.stage} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{item.file.name}</span>
                      <span
                        className={cn(
                          'text-xs',
                          item.stage === 'failed' ? 'text-destructive' : 'text-muted-foreground',
                        )}
                      >
                        {item.message ?? formatBytes(item.file.size)}
                      </span>
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={uploading}
                      aria-label={`Remove ${item.file.name}`}
                      onClick={() =>
                        setQueue((current) => current.filter((other) => other.id !== item.id))
                      }
                    >
                      <Trash2 className="size-4" aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
            ) : null}

            <Field orientation="horizontal">
              <Button type="submit" disabled={uploading} aria-busy={uploading}>
                {uploading ? <Spinner /> : <Upload className="size-4" aria-hidden />}
                {uploadLabel(uploading, pending.length)}
              </Button>
              {queue.length > 0 && !uploading ? (
                <Button type="button" variant="ghost" onClick={() => setQueue([])}>
                  Clear
                </Button>
              ) : null}
            </Field>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}

/** Same file, dropped twice — name, size and mtime together are as close as the browser gets. */
function identity({ file }: { file: File }): string {
  return `${file.name}:${file.size}:${file.lastModified}`
}

function uploadLabel(uploading: boolean, pending: number): string {
  if (uploading) return 'Uploading…'
  if (pending > 1) return `Upload ${pending} files`
  return 'Upload'
}

function StageIcon({ stage }: { stage: Stage }) {
  if (stage === 'uploading') return <Spinner className="text-muted-foreground size-4" />
  if (stage === 'done') return <CircleCheck className="size-4 text-emerald-600" aria-hidden />
  if (stage === 'failed') return <CircleAlert className="text-destructive size-4" aria-hidden />
  return <Upload className="text-muted-foreground size-4" aria-hidden />
}
