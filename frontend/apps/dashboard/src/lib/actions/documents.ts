'use server'

import { revalidatePath } from 'next/cache'

import { type ActionState, failed, fromError, succeeded } from '@/lib/action-state'
import { authenticatedApi } from '@/lib/api'
import { text } from '@/lib/form'
import { rejectionReason } from '@/lib/uploads'

function documentsPath(chatbotId: string): string {
  return `/chatbots/${chatbotId}/documents`
}

/**
 * Queue one or more documents for ingestion.
 *
 * `getAll`, because the file input is `multiple` and the two paths into here disagree about
 * how many files one call carries. With scripts running, the uploader sends one file per call
 * so each gets its own outcome and no single request body has to hold the whole selection.
 * Without them the browser posts the entire selection at once, and this loop is the only
 * thing that sees the rest of it.
 */
export async function uploadDocumentAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const chatbotId = text(formData, 'chatbot_id')
  if (!chatbotId) {
    return failed('Missing chatbot reference.')
  }

  const files = formData.getAll('file').filter((entry) => entry instanceof File)
  if (files.length === 0) {
    return failed('Choose a file to upload.')
  }

  const api = await authenticatedApi()
  const queued: string[] = []
  const refused: string[] = []

  for (const file of files) {
    const reason = rejectionReason(file)
    if (reason) {
      refused.push(`${file.name}: ${reason}`)
      continue
    }

    try {
      await api.uploadDocument(chatbotId, file)
      queued.push(file.name)
    } catch (error) {
      // One bad file does not condemn the rest of the selection, so this collects the reason
      // and carries on rather than returning on the first failure.
      refused.push(`${file.name}: ${fromError(error).message ?? 'Upload failed.'}`)
    }
  }

  if (queued.length > 0) {
    revalidatePath(documentsPath(chatbotId))
  }

  if (refused.length === 0) {
    // Accepted, not finished: the worker parses and embeds it, and the table polls until the
    // status settles.
    return succeeded(queuedMessage(queued))
  }
  // A partial success is still a failure to report — silently dropping the files that did not
  // make it would be the one outcome the user cannot see from the table.
  return failed(
    [queued.length > 0 ? queuedMessage(queued) : '', ...refused].filter(Boolean).join(' '),
  )
}

function queuedMessage(names: string[]): string {
  return names.length === 1
    ? `${names[0]} was queued for ingestion.`
    : `${names.length} files were queued for ingestion.`
}

export async function reprocessDocumentAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const chatbotId = text(formData, 'chatbot_id')
  const documentId = text(formData, 'document_id')
  if (!chatbotId || !documentId) return failed('That document could not be identified.')

  const api = await authenticatedApi()
  try {
    await api.reprocessDocument(chatbotId, documentId)
    revalidatePath(documentsPath(chatbotId))
    return succeeded('Queued for reprocessing.')
  } catch (error) {
    return fromError(error)
  }
}

export async function deleteDocumentAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const chatbotId = text(formData, 'chatbot_id')
  const documentId = text(formData, 'document_id')
  if (!chatbotId || !documentId) return failed('That document could not be identified.')

  const api = await authenticatedApi()
  try {
    await api.deleteDocument(chatbotId, documentId)
    revalidatePath(documentsPath(chatbotId))
    return succeeded('Document deleted, along with its passages.')
  } catch (error) {
    return fromError(error)
  }
}
