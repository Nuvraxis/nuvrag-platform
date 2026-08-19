'use client'

import type { CSSProperties } from 'react'

import type { ThemeFormValues } from '@/lib/widget-theme'

/**
 * What the widget will look like, drawn from the same custom properties the real one uses.
 *
 * It is a deliberate copy of `widget.css` rather than the file itself: the widget ships to
 * other people's sites as its own bundle and must not grow a dependency on the dashboard.
 * The variable names are the contract between the two, so a colour that lands here lands
 * there — but a layout change in the widget has to be repeated, and this is only ever meant
 * to be a fair impression of the panel, not a pixel-exact mirror of it.
 */
export function WidgetPreview({
  theme,
  name,
  greeting,
}: {
  theme: ThemeFormValues
  name: string
  greeting: string
}) {
  // Only the links that were filled in, in the order the widget shows them. Whitespace-only
  // counts as empty here exactly as it does server-side, so the preview does not promise a
  // footer entry the widget will drop.
  const legal = [
    theme.privacy_url?.trim() ? 'Privacy' : null,
    theme.terms_url?.trim() ? 'Terms' : null,
  ].filter((label): label is string => label !== null)

  const radius = Number(theme.radius)
  const style = {
    '--accent': theme.accent,
    '--accent-foreground': theme.accent_foreground,
    '--surface': theme.surface,
    '--surface-muted': theme.surface_muted,
    '--border': theme.border,
    '--text': theme.text,
    '--text-muted': theme.text_muted,
    borderRadius: `${Number.isFinite(radius) ? radius : 16}px`,
    background: 'var(--surface)',
    borderColor: 'var(--border)',
    color: 'var(--text)',
  } as CSSProperties

  return (
    <div className="flex flex-col items-center gap-4" aria-hidden="true">
      <div
        data-preview="panel"
        style={style}
        className="w-full max-w-sm overflow-hidden border text-[15px] leading-relaxed shadow-sm"
      >
        <div
          data-preview="header"
          className="flex items-center justify-between gap-3 px-4 py-3"
          style={{ background: 'var(--accent)', color: 'var(--accent-foreground)' }}
        >
          <span className="truncate text-[15px] font-semibold">{name}</span>
          <span className="text-lg leading-none opacity-80">×</span>
        </div>

        <div className="flex flex-col gap-3 p-4">
          <Bubble side="left" background="var(--surface-muted)" color="var(--text)">
            {greeting}
          </Bubble>
          <Bubble side="right" background="var(--accent)" color="var(--accent-foreground)">
            Do you ship to Ireland?
          </Bubble>
          <Bubble side="left" background="var(--surface-muted)" color="var(--text)">
            Yes — orders over €50 ship free, and everything else is a flat €4.95. [1]
          </Bubble>
          <span
            className="w-fit rounded-full border px-2 py-0.5 text-xs"
            style={{
              background: 'var(--surface-muted)',
              borderColor: 'var(--border)',
              color: 'var(--text-muted)',
            }}
          >
            [1] Shipping
          </span>
        </div>

        <div
          className="flex items-center gap-2 border-t p-3"
          style={{ borderColor: 'var(--border)' }}
        >
          <span
            className="flex-1 rounded-[10px] border px-3 py-2 text-sm"
            style={{
              background: 'var(--surface-muted)',
              borderColor: 'var(--border)',
              color: 'var(--text-muted)',
            }}
          >
            Ask anything…
          </span>
          <span
            className="rounded-[10px] px-4 py-2 text-sm font-semibold"
            style={{ background: 'var(--accent)', color: 'var(--accent-foreground)' }}
          >
            Send
          </span>
        </div>

        <div
          className="flex flex-col gap-0.5 px-3 pb-3 text-center text-[11px]"
          style={{ color: 'var(--text-muted)' }}
        >
          <span>Answers are generated from this site&rsquo;s documents.</span>
          {/* Text, not anchors: this is a picture of the widget inside the dashboard, and a
              working link here would navigate the person editing the settings away. The
              widget renders the same two entries, with the same separator. */}
          {legal.length > 0 ? (
            <span>
              {legal.map((label, index) => (
                <span key={label}>
                  {index > 0 ? <span className="px-1.5 opacity-60">·</span> : null}
                  <span className="underline">{label}</span>
                </span>
              ))}
            </span>
          ) : null}
          <span className="opacity-75">
            Powered by <span className="underline">Nuvraxis</span>
          </span>
        </div>
      </div>

      <div
        data-preview="launcher-row"
        className={`flex w-full max-w-sm ${theme.position === 'left' ? 'justify-start' : 'justify-end'}`}
      >
        <span
          className="flex size-12 items-center justify-center rounded-full text-xl shadow-md"
          style={{ background: theme.accent, color: theme.accent_foreground }}
        >
          💬
        </span>
      </div>
    </div>
  )
}

function Bubble({
  side,
  background,
  color,
  children,
}: {
  side: 'left' | 'right'
  background: string
  color: string
  children: string
}) {
  return (
    <span
      className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
        side === 'right' ? 'self-end rounded-br-sm' : 'self-start rounded-bl-sm'
      }`}
      style={{ background, color }}
    >
      {children}
    </span>
  )
}
