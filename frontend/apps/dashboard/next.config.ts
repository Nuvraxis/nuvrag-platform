import path from 'node:path'
import { fileURLToPath } from 'node:url'

import type { NextConfig } from 'next'

const here = path.dirname(fileURLToPath(import.meta.url))

const config: NextConfig = {
  reactStrictMode: true,

  experimental: {
    // A document upload travels to the API inside a Server Action, and action bodies are
    // capped at 1 MB by default — so without this the 25 MB the API accepts is unreachable
    // and anything larger than a small text file fails before it leaves the dashboard. The
    // extra megabyte is headroom for the multipart boundaries and part headers, which count
    // towards the same limit. The uploader sends one file per request precisely so that this
    // ceiling stays the size of one document rather than of a whole selection.
    serverActions: { bodySizeLimit: '26mb' },
  },

  // The Docker image copies `.next/standalone`, which only contains the files Next traced as
  // reachable. In a workspace those live above the app, so tracing has to start at the repo.
  output: 'standalone',
  outputFileTracingRoot: path.join(here, '../..'),

  // Workspace packages are published as TypeScript source rather than built artefacts, so
  // Next compiles them alongside the app.
  transpilePackages: ['@rag/api-client', '@rag/types', '@rag/ui'],

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'x-content-type-options', value: 'nosniff' },
          { key: 'x-frame-options', value: 'DENY' },
          { key: 'referrer-policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'permissions-policy',
            value: 'camera=(), microphone=(), geolocation=(), interest-cohort=()',
          },
          // Only meaningful over HTTPS; browsers ignore it on plain HTTP, so it is safe to
          // send unconditionally rather than gating it on a runtime check.
          {
            key: 'strict-transport-security',
            value: 'max-age=63072000; includeSubDomains; preload',
          },
        ],
      },
    ]
  },
}

export default config
