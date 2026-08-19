import type { ComponentProps } from 'react'

import { cn } from '../lib/utils'

/**
 * A plain `<select>`, styled to match `Input`.
 *
 * Deliberately not shadcn's Select, which is built on a Radix listbox and renders nothing
 * usable until JavaScript has run. Every form in this dashboard is a Server Action that
 * submits without client JavaScript, and a control that disappears in that state would take
 * the form with it.
 */
export function NativeSelect({ className, ...props }: ComponentProps<'select'>) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        'border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs',
        'dark:bg-input/30 transition-[color,box-shadow] outline-none md:text-sm',
        'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        'aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40',
        className,
      )}
      {...props}
    />
  )
}
