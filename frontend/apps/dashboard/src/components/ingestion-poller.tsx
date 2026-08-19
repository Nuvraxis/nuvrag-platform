'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

const INTERVAL_MS = 4000

/**
 * Ingestion happens on a Celery worker, so an upload returns 202 and the row settles a few
 * seconds later. This refetches the server component while anything is still in flight and
 * stops as soon as nothing is, rather than polling a quiet page forever.
 */
export function IngestionPoller({ active }: { active: boolean }) {
  const router = useRouter()

  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => router.refresh(), INTERVAL_MS)
    return () => clearInterval(timer)
  }, [active, router])

  return null
}
