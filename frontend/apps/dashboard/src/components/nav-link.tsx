'use client'

import { cn } from '@rag/ui'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

export interface NavLinkProps {
  href: string
  children: ReactNode
  /** Match nested routes too, e.g. `/chatbots/x` highlighting `/chatbots`. */
  exact?: boolean
  className?: string
  activeClassName?: string
}

export function NavLink({
  href,
  children,
  exact = false,
  className,
  activeClassName = 'bg-accent text-primary',
}: NavLinkProps) {
  const pathname = usePathname()
  const active = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`)

  return (
    <Link
      href={href}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors',
        active ? activeClassName : 'text-muted-foreground hover:bg-muted hover:text-foreground',
        className,
      )}
    >
      {children}
    </Link>
  )
}
