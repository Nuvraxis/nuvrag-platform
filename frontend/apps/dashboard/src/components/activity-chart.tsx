import type { DailyActivityPoint } from '@rag/api-client'

import { formatDay } from '@/lib/format'

const WIDTH = 720
const HEIGHT = 180
const PADDING_BOTTOM = 20
const SERIES = [
  { key: 'messages', label: 'Messages', className: 'fill-primary' },
  { key: 'conversations', label: 'Conversations', className: 'fill-success' },
] as const

/**
 * Grouped bars, drawn as plain SVG.
 *
 * A charting library would be several times the size of everything else on this page, and
 * the only interaction worth having — reading the number for a day — is covered by a native
 * `<title>` tooltip.
 */
export function ActivityChart({ points }: { points: DailyActivityPoint[] }) {
  const peak = Math.max(1, ...points.flatMap((point) => [point.messages, point.conversations]))
  const slot = WIDTH / Math.max(points.length, 1)
  const barWidth = Math.max(2, (slot - 4) / SERIES.length)
  const plotHeight = HEIGHT - PADDING_BOTTOM
  const labelEvery = Math.max(1, Math.ceil(points.length / 8))

  return (
    <figure className="space-y-3">
      <figcaption className="text-muted-foreground flex flex-wrap gap-4 text-xs">
        {SERIES.map((series) => (
          <span key={series.key} className="inline-flex items-center gap-1.5">
            <svg width="10" height="10" aria-hidden className="shrink-0">
              <rect width="10" height="10" rx="2" className={series.className} />
            </svg>
            {series.label}
          </span>
        ))}
        <span className="ml-auto">Peak {peak} per day</span>
      </figcaption>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-44 w-full"
        role="img"
        aria-label={`Daily activity over the last ${points.length} days`}
      >
        <line
          x1="0"
          y1={plotHeight}
          x2={WIDTH}
          y2={plotHeight}
          className="stroke-input"
          strokeWidth="1"
        />

        {points.map((point, index) => (
          <g key={point.day} transform={`translate(${index * slot} 0)`}>
            {SERIES.map((series, seriesIndex) => {
              const value = point[series.key]
              const height = (value / peak) * (plotHeight - 4)
              return (
                <rect
                  key={series.key}
                  x={2 + seriesIndex * barWidth}
                  y={plotHeight - height}
                  width={barWidth - 1}
                  height={height}
                  rx="1"
                  className={series.className}
                >
                  <title>{`${formatDay(point.day)}: ${value} ${series.label.toLowerCase()}`}</title>
                </rect>
              )
            })}

            {index % labelEvery === 0 ? (
              <text
                x={slot / 2}
                y={HEIGHT - 4}
                textAnchor="middle"
                className="text-muted-foreground fill-current text-[10px]"
              >
                {formatDay(point.day)}
              </text>
            ) : null}
          </g>
        ))}
      </svg>
    </figure>
  )
}
