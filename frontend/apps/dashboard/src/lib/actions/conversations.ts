'use server'

import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'

import { type ActionState, failed, fromError } from '@/lib/action-state'
import { authenticatedApi } from '@/lib/api'
import { text } from '@/lib/form'

export async function deleteConversationAction(
  _previous: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const chatbotId = text(formData, 'chatbot_id')
  const conversationId = text(formData, 'conversation_id')
  if (!chatbotId || !conversationId) {
    return failed('That conversation could not be identified.')
  }

  const api = await authenticatedApi()
  try {
    await api.deleteConversation(chatbotId, conversationId)
  } catch (error) {
    return fromError(error)
  }

  // Outside the try, as in `deleteChatbotAction`: `redirect` reports itself by throwing, and
  // catching that would turn a successful delete into an error message.
  revalidatePath(`/chatbots/${chatbotId}/conversations`)
  redirect(`/chatbots/${chatbotId}/conversations`)
}
