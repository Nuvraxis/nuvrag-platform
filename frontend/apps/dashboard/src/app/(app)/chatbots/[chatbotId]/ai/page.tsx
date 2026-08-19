import type { Metadata } from 'next'

import { ChatbotAIForm } from '@/components/chatbot-ai-form'
import { loadAIConfig } from '@/lib/ai-config'
import { Suspense } from 'react'
import PageLoading from '@/components/page-loading'

export const metadata: Metadata = { title: 'AI provider' }


 async function AIProvider({
  params,
}: {
  params: Promise<{ chatbotId: string }>
}) {
  const { chatbotId } = await params
  const config = await loadAIConfig(chatbotId)

  return <ChatbotAIForm chatbotId={chatbotId} config={config} />
}


export default async function AIProviderPage({
  params,
}: {
  params: Promise<{ chatbotId: string }>
}) {
 
  return (
    <Suspense fallback={<PageLoading />}>
      <AIProvider params={params} />
    </Suspense>
  )
}