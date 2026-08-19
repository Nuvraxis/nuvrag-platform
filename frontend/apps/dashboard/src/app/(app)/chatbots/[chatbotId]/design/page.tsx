import type { Metadata } from 'next'

import { ChatbotDesignForm } from '@/components/chatbot-design-form'
import { fetchApi } from '@/lib/api'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

export const metadata: Metadata = { title: 'Design' }

async function DesignChatBot({ params }: { params: Promise<{ chatbotId: string }> }) {
  const { chatbotId } = await params
  const chatbot = await fetchApi((api) => api.getChatbot(chatbotId))

  return <ChatbotDesignForm chatbot={chatbot} />
}

// The boundary buys a skeleton instead of a blank tab while the chatbot loads. The cost is
// paid only by a visitor with no JavaScript: content streamed into a boundary arrives at the
// end of the document and is moved into place by an inline script, so if the fetch outruns
// the shell flush they are left looking at the fallback. Every other page here makes the
// same trade.
export default async function DesignPage({ params }: { params: Promise<{ chatbotId: string }> }) {
  return (
    <Suspense fallback={<PageLoading />}>
      <DesignChatBot params={params} />
    </Suspense>
  )
}
