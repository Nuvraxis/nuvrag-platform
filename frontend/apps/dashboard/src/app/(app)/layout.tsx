import type { ReactNode } from 'react'

import { AppSidebar } from '@/components/app-sidebar'
import { fetchApi } from '@/lib/api'

export default async function AppLayout({ children }: { children: ReactNode }) {
  // Both calls hit the API on every navigation. That is deliberate: the sidebar has to show
  // a chatbot the moment it is created, and neither response is large enough to be worth a
  // cache that would then need invalidating from four different actions.
  const [user, chatbots] = await Promise.all([
    fetchApi((api) => api.me()),
    fetchApi((api) => api.listChatbots({ limit: 100 })),
  ])

  return (
    <div className="flex min-h-dvh flex-col lg:flex-row">
      <AppSidebar user={user} chatbots={chatbots.items} />
      <main className="min-w-0 flex-1 px-6 py-8 lg:h-dvh lg:overflow-y-auto lg:px-10">
        {children}
      </main>
    </div>
  )
}
