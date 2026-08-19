import { Toaster } from '@rag/ui'
import type { Metadata, Viewport } from 'next'
import type { ReactNode } from 'react'
import { Poppins, Libre_Baskerville, IBM_Plex_Mono } from 'next/font/google'

import './globals.css'

export const metadata: Metadata = {
  title: { default: 'RAG Platform', template: '%s · RAG Platform' },
  description: 'Manage chatbots, documents and embed snippets for your organisation.',
  // The dashboard is behind a login and has nothing worth indexing.
  robots: { index: false, follow: false },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
}

const fontSans = Poppins({
  subsets: ['latin'],
  variable: '--font-sans',
  weight: '400',
})

const fontSerif = Libre_Baskerville({
  subsets: ['latin'],
  variable: '--font-serif',
})

const fontMono = IBM_Plex_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  weight: '400',
})

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        className={`min-h-dvh ${fontSans.variable} ${fontSerif.variable} ${fontMono.variable} antialiased`}
      >
        {children}
        {/* One mount for the whole app: every action reports through it, and a toaster per
            route group would leave a second one behind on navigation. */}
        <Toaster position="top-right" closeButton richColors={false} />
      </body>
    </html>
  )
}
