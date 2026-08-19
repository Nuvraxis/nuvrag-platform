const NUMBER = new Intl.NumberFormat('en')

const DATE_TIME = new Intl.DateTimeFormat('en', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'UTC',
})

const DAY = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', timeZone: 'UTC' })

/**
 * Everything is rendered in UTC on purpose. The server and the browser must agree or React
 * flags a hydration mismatch, and the API stores and returns UTC throughout.
 */
export function formatDateTime(value: string): string {
  return `${DATE_TIME.format(new Date(value))} UTC`
}

export function formatDay(value: string): string {
  return DAY.format(new Date(`${value}T00:00:00Z`))
}

export function formatNumber(value: number): string {
  return NUMBER.format(value)
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let size = bytes / 1024
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`
}

export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds == null) return '—'
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`
  return `${(milliseconds / 1000).toFixed(1)} s`
}

/** "3 minutes ago" for timestamps in the recent past, falling back to an absolute date. */
export function formatRelative(value: string, now = Date.now()): string {
  const elapsed = now - new Date(value).getTime()
  const minutes = Math.round(elapsed / 60_000)

  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`

  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`

  const days = Math.round(hours / 24)
  if (days <= 7) return `${days} day${days === 1 ? '' : 's'} ago`

  return formatDateTime(value)
}
