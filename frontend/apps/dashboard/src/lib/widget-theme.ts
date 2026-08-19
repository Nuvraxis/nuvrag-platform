import type { WidgetTheme } from '@rag/api-client'

/**
 * The colours `widget.css` falls back to when a chatbot has no theme of its own.
 *
 * Kept here so the design form and its preview start from what the widget would actually
 * render rather than from something invented for the dashboard. They are a copy, not the
 * source: a widget release can move them, and any chatbot that has never been themed moves
 * with it — which is the whole reason an unset value is stored as absent rather than filled
 * in at creation time.
 */
export const WIDGET_DEFAULTS = {
  accent: '#2563eb',
  accent_foreground: '#ffffff',
  surface: '#ffffff',
  surface_muted: '#f1f5f9',
  border: '#e2e8f0',
  text: '#0f172a',
  text_muted: '#64748b',
  radius: 16,
  scheme: 'system',
  position: 'right',
} as const

export type ThemeColour = Extract<
  keyof typeof WIDGET_DEFAULTS,
  'accent' | 'accent_foreground' | 'surface' | 'surface_muted' | 'border' | 'text' | 'text_muted'
>

export interface ColourControl {
  name: ThemeColour
  label: string
  description: string
}

/** The two groups the form shows: what a tenant brands, and what the panel is made of. */
export const BRAND_COLOURS: readonly ColourControl[] = [
  {
    name: 'accent',
    label: 'Accent',
    description: 'Header, launcher, send button and the visitor’s own messages.',
  },
  {
    name: 'accent_foreground',
    label: 'Accent text',
    description: 'Text and icons drawn on top of the accent.',
  },
]

export const PANEL_COLOURS: readonly ColourControl[] = [
  { name: 'surface', label: 'Panel', description: 'The background behind the conversation.' },
  {
    name: 'surface_muted',
    label: 'Panel accent',
    description: 'Replies, the composer and source chips.',
  },
  { name: 'border', label: 'Border', description: 'Panel edge, composer and chip outlines.' },
  { name: 'text', label: 'Text', description: 'Message text.' },
  { name: 'text_muted', label: 'Secondary text', description: 'Sources and the footer note.' },
] as const

export const ALL_COLOURS: readonly ColourControl[] = [...BRAND_COLOURS, ...PANEL_COLOURS]

/** Form values, which — unlike the stored theme — always have every member filled in. */
export interface ThemeFormValues {
  accent: string
  accent_foreground: string
  surface: string
  surface_muted: string
  border: string
  text: string
  text_muted: string
  radius: number | string
  scheme: 'system' | 'light' | 'dark'
  position: 'right' | 'left'
  title: string
  greeting: string
  // Not part of `theme_json` — they are their own columns, and they survive the reset that
  // empties the theme. They travel with these values because they are edited on the same
  // form and drawn in the same preview.
  privacy_url: string
  terms_url: string
}

export function themeFormDefaults(
  theme: WidgetTheme | undefined,
  links: { privacy_url?: string; terms_url?: string } = {},
): ThemeFormValues {
  const stored = theme ?? {}
  return {
    accent: stored.accent ?? WIDGET_DEFAULTS.accent,
    accent_foreground: stored.accent_foreground ?? WIDGET_DEFAULTS.accent_foreground,
    surface: stored.surface ?? WIDGET_DEFAULTS.surface,
    surface_muted: stored.surface_muted ?? WIDGET_DEFAULTS.surface_muted,
    border: stored.border ?? WIDGET_DEFAULTS.border,
    text: stored.text ?? WIDGET_DEFAULTS.text,
    text_muted: stored.text_muted ?? WIDGET_DEFAULTS.text_muted,
    radius: stored.radius ?? WIDGET_DEFAULTS.radius,
    scheme: stored.scheme ?? WIDGET_DEFAULTS.scheme,
    position: stored.position ?? WIDGET_DEFAULTS.position,
    title: stored.title ?? '',
    greeting: stored.greeting ?? '',
    privacy_url: links.privacy_url ?? '',
    terms_url: links.terms_url ?? '',
  }
}
