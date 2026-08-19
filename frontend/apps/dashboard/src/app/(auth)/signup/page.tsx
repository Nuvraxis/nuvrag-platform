import type { Metadata } from 'next'

import { SignupForm } from '@/components/signup-form'

export const metadata: Metadata = { title: 'Create an organisation' }

export default function SignupPage() {
  return <SignupForm />
}
