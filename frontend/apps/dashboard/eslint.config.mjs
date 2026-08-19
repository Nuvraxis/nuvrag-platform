import next from '@rag/config/eslint/next'

const config = [...next, { ignores: ['.next/**', 'next-env.d.ts'] }]

export default config
