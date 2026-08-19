import { buttonVariants, Card, CardContent } from '@rag/ui'
import Link from 'next/link'

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col justify-center px-6">
      <Card>
        <CardContent className="space-y-4">
          <h1 className="text-foreground text-lg font-semibold">Not found</h1>
          <p className="text-muted-foreground text-sm">
            This page does not exist, or it belongs to a different organisation.
          </p>
          <Link href="/chatbots" className={buttonVariants()}>
            Back to chatbots
          </Link>
        </CardContent>
      </Card>
    </main>
  )
}
