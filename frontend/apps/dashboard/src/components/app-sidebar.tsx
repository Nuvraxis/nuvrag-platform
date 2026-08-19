import type { Chatbot, User } from '@rag/api-client'
import { Button } from '@rag/ui'
import { Bot, LifeBuoy, LogOut, Plus, Users } from 'lucide-react'
import Link from 'next/link'

import { logoutAction } from '@/lib/actions/auth'

import { NavLink } from './nav-link'

export interface AppSidebarProps {
  user: User
  chatbots: Chatbot[]
}

export function AppSidebar({ user, chatbots }: AppSidebarProps) {
  return (
    <aside className="border-border bg-card flex shrink-0 flex-col gap-6 border-b px-4 py-5 lg:h-dvh lg:w-64 lg:border-r lg:border-b-0">
      <Link href="/chatbots" className="flex items-center gap-2 px-2">
        <span className="bg-primary text-primary-foreground grid size-8 place-items-center rounded-md">
          <Bot className="size-5" aria-hidden />
        </span>
        <span className="text-foreground font-semibold">NuvRAG</span>
      </Link>

      <nav aria-label="Chatbots" className="flex min-h-0 flex-1 flex-col gap-1">
        <div className="flex items-center justify-between px-3 pb-1">
          <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            Chatbots
          </span>
          <Link
            href="/chatbots/new"
            aria-label="New chatbot"
            className="text-muted-foreground hover:bg-accent hover:text-primary rounded-md p-1"
          >
            <Plus className="size-4" aria-hidden />
          </Link>
        </div>

        <div className="flex max-h-56 flex-col gap-1 overflow-y-auto lg:max-h-none">
          {chatbots.length === 0 ? (
            <p className="text-muted-foreground px-3 py-2 text-sm">Nothing here yet.</p>
          ) : (
            chatbots.map((chatbot) => (
              <NavLink key={chatbot.id} href={`/chatbots/${chatbot.id}`}>
                <span className="truncate">{chatbot.name}</span>
              </NavLink>
            ))
          )}
        </div>

        <NavLink href="/chatbots" exact className="mt-2">
          All chatbots
        </NavLink>
        <NavLink href="/tickets">
          <LifeBuoy className="size-4 shrink-0" aria-hidden />
          Tickets
        </NavLink>
        <NavLink href="/team">
          <Users className="size-4 shrink-0" aria-hidden />
          Team
        </NavLink>
      </nav>

      <div className="border-border space-y-3 border-t pt-4">
        <div className="px-3">
          <p className="text-foreground truncate text-sm font-medium">
            {user.full_name ?? user.email}
          </p>
          <p className="text-muted-foreground truncate text-xs">
            {user.email} · {user.role}
          </p>
        </div>
        <form action={logoutAction}>
          <Button type="submit" variant="ghost" size="sm" className="w-full justify-start">
            <LogOut className="size-4" aria-hidden />
            Sign out
          </Button>
        </form>
      </div>
    </aside>
  )
}
