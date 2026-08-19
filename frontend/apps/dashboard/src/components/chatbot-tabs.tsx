'use client'

import { cn } from '@rag/ui'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

const TABS = [
  { segment: '', label: 'Overview' },
  { segment: 'documents', label: 'Documents' },
  { segment: 'conversations', label: 'Conversations' },
  { segment: 'ai', label: 'AI provider' },
  { segment: 'design', label: 'Design' },
  { segment: 'embed', label: 'Embed' },
  { segment: 'settings', label: 'Settings' },
] as const

export function ChatbotTabs({ chatbotId }: { chatbotId: string }) {
  const pathname = usePathname()
  const base = `/chatbots/${chatbotId}`

  return (
    <nav aria-label="Chatbot sections" className="border-border mb-6 border-b">
      <ul className="-mb-px flex gap-1 overflow-x-auto">
        {TABS.map(({ segment, label }) => {
          const href = segment ? `${base}/${segment}` : base
          const active = segment
            ? pathname === href || pathname.startsWith(`${href}/`)
            : pathname === base

          return (
            <li key={label}>
              <Link
                href={href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'inline-block border-b-2 px-3 py-2 text-sm whitespace-nowrap transition-colors',
                  active
                    ? 'border-primary text-primary font-medium'
                    : 'text-muted-foreground hover:border-input hover:text-foreground border-transparent',
                )}
              >
                {label}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
