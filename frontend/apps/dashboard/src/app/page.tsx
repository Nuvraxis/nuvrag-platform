import { redirect } from 'next/navigation'

export default function IndexPage() {
  // The proxy has already decided whether this visitor is signed in; if they are not, this
  // redirect never runs because they were sent to /login first.
  redirect('/chatbots')
}
