'use client'

import { Button } from '@rag/ui'
import { Check, Copy } from 'lucide-react'
import { type ComponentProps, useEffect, useState } from 'react'

export interface CopyButtonProps extends Omit<
  ComponentProps<typeof Button>,
  'onClick' | 'children'
> {
  value: string
  label?: string
}

export function CopyButton({ value, label = 'Copy', ...props }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(timer)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
    } catch {
      // Clipboard access is denied outside a secure context; selecting the text still works.
      setCopied(false)
    }
  }

  return (
    // Explicitly not a submit: shadcn's Button leaves `type` to the HTML default, which
    // inside a form is submit, and this one sits beside the fields on the embed page.
    <Button type="button" variant="secondary" size="sm" onClick={copy} {...props}>
      {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
      {copied ? 'Copied' : label}
    </Button>
  )
}
