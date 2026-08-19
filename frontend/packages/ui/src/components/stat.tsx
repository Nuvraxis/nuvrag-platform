import type { ReactNode } from 'react'

import { Card, CardContent } from './ui/card'

export interface StatProps {
  label: string
  value: ReactNode
  hint?: ReactNode
}

/** A single number with its label — the building block of the overview grid. */
export function Stat({ label, value, hint }: StatProps) {
  return (
    <Card>
      <CardContent>
        <p className="text-muted-foreground text-sm">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        {hint ? <p className="text-muted-foreground mt-1 text-xs">{hint}</p> : null}
      </CardContent>
    </Card>
  )
}
