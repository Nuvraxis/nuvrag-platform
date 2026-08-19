import type { Metadata } from 'next'
import type { ReactNode } from 'react'

import { ChatbotTabs } from '@/components/chatbot-tabs'
import { PageHeader } from '@/components/page-header'
import { ChatbotStatusBadge } from '@/components/status-badge'
import { fetchApi } from '@/lib/api'

interface LayoutProps {
  children: ReactNode
  params: Promise<{ chatbotId: string }>
}

export async function generateMetadata({ params }: LayoutProps): Promise<Metadata> {
  const { chatbotId } = await params
  const chatbot = await fetchApi((api) => api.getChatbot(chatbotId))
  return { title: chatbot.name }
}

export default async function ChatbotLayout({ children, params }: LayoutProps) {
  const { chatbotId } = await params
  const chatbot = await fetchApi((api) => api.getChatbot(chatbotId))

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title={chatbot.name}
        description={chatbot.description ?? `Slug: ${chatbot.slug}`}
        actions={<ChatbotStatusBadge status={chatbot.status} />}
      />
      <ChatbotTabs chatbotId={chatbot.id} />
      {children}
    </div>
  )
}
