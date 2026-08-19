import { UPLOAD_EXTENSIONS } from '@rag/types'

/**
 * Mirrors `INGESTION_MAX_UPLOAD_BYTES`, which the API enforces again on arrival.
 *
 * `serverActions.bodySizeLimit` in `next.config.ts` is deliberately set above this: an upload
 * reaches the API through a Server Action, and that body is capped separately.
 */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024

export const SUPPORTED_FORMATS = UPLOAD_EXTENSIONS.join(', ')

/**
 * Why this file cannot be ingested, or `null` if it can.
 *
 * Shared by the browser and the Server Action so that a file turned away in the queue and one
 * turned away on the server are refused for the same reason, in the same words. The check in
 * the browser is a courtesy — it saves the transfer — and the one in the action is the one
 * that counts, since anyone can POST to an action without going through this UI.
 */
export function rejectionReason(file: File): string | null {
  if (file.size === 0) return 'That file is empty.'
  if (file.size > MAX_UPLOAD_BYTES) return 'Larger than the 25 MB limit.'

  const name = file.name.toLowerCase()
  if (!UPLOAD_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return `Supported formats are ${SUPPORTED_FORMATS}.`
  }
  return null
}
