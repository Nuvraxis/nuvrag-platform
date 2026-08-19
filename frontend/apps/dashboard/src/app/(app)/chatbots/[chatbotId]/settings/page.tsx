import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@rag/ui'
import type { Metadata } from 'next'

import { ActionForm } from '@/components/action-form'
import { ChatbotSettingsForm } from '@/components/chatbot-settings-form'
import { ConfirmSubmit } from '@/components/confirm-submit'
import { deleteChatbotAction } from '@/lib/actions/chatbots'
import { fetchApi } from '@/lib/api'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

export const metadata: Metadata = { title: 'Settings' }

async function Settings({ params }: { params: Promise<{ chatbotId: string }> }) {
  const { chatbotId } = await params
  const chatbot = await fetchApi((api) => api.getChatbot(chatbotId))

  return (
    <div className="space-y-6">
      <ChatbotSettingsForm chatbot={chatbot} />

      <Card className="border-destructive/40">
        <CardHeader>
          <div className="space-y-1">
            <CardTitle className="text-destructive">Delete this chatbot</CardTitle>
            <CardDescription>
              Its documents, indexed passages and conversation history are removed with it. This
              cannot be undone.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <ActionForm action={deleteChatbotAction} announceSuccess={false}>
            <input type="hidden" name="chatbot_id" value={chatbot.id} />
            <ConfirmSubmit
              variant="destructive"
              confirmTitle={`Delete ${chatbot.name}?`}
              confirmDescription="Its documents and conversations go with it. This cannot be undone."
              confirmLabel="Delete chatbot"
              pendingLabel="Deleting…"
            >
              Delete {chatbot.name}
            </ConfirmSubmit>
          </ActionForm>
        </CardContent>
      </Card>
    </div>
  )
}

export default async function SettingsPage({ params }: { params: Promise<{ chatbotId: string }> }) {
  return (
    <Suspense fallback={<PageLoading />}>
      <Settings params={params} />
    </Suspense>
  )
}
