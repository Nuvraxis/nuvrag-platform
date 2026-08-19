import type { ReactNode } from 'react'

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-8 px-6 py-12">
      <div className="space-y-1">
        <p className="text-primary text-sm font-medium tracking-wide uppercase">RAG Platform</p>
        <h1 className="text-foreground text-2xl font-semibold">Chatbots for your own content</h1>
      </div>
      {children}
    </main>
  )
}
