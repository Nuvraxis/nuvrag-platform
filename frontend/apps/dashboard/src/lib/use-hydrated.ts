'use client'

import { useSyncExternalStore } from 'react'

const subscribe = () => () => {}

/**
 * Whether React is running in this browser yet.
 *
 * For affordances that only make sense once scripts are: a control disabled by client state
 * would otherwise be rendered disabled on the server too, and a visitor with JavaScript off
 * would receive a permanently dead button rather than a form that still posts.
 *
 * `useSyncExternalStore` rather than an effect, because the two snapshots say exactly this —
 * one value on the server, another on the client — without a state update to schedule.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  )
}
