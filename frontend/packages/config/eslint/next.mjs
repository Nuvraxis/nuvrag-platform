import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'
import tseslint from 'typescript-eslint'

import { base } from './base.mjs'

// `next/core-web-vitals` already registers the React and react-hooks plugins, so this
// extends `base` rather than `react` — flat config rejects a plugin key being defined twice.
export const next = tseslint.config(...base, ...nextCoreWebVitals)

export default next
