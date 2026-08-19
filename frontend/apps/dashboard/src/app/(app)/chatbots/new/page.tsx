import type { Metadata } from 'next'

import { CreateChatbotForm } from '@/components/create-chatbot-form'
import { PageHeader } from '@/components/page-header'

export const metadata: Metadata = { title: 'New chatbot' }

export default function NewChatbotPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="New chatbot"
        description="Only the name is required; everything here can be changed later."
      />
      <CreateChatbotForm />
    </div>
  )
}
