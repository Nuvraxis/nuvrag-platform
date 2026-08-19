import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

import { base } from './base.mjs'

/**
 * Shared component packages: React rules without the Next.js-specific ones.
 *
 * `configs.recommended` is still the eslintrc shape in this plugin; `flat.recommended` is
 * the one ESLint 10 can actually load.
 */
export const react = tseslint.config(...base, reactHooks.configs.flat.recommended)

export default react
