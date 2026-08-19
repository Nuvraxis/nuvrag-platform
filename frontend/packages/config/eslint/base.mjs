import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import tseslint from 'typescript-eslint'

/** Rules every package in the workspace gets, framework-agnostic. */
export const base = tseslint.config(
  { ignores: ['**/dist/**', '**/.next/**', '**/.turbo/**', '**/node_modules/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      // An unused binding is usually a leftover, but `_`-prefixed ones are a deliberate
      // signal that a positional argument is being skipped.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // Deliberately no type-aware rules here. They need a TypeScript program per file,
      // which triples lint time and breaks outright under the parser `eslint-config-next`
      // substitutes for its own files.
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
  // Last, so formatting-adjacent rules never fight Prettier.
  prettier,
)

export default base
