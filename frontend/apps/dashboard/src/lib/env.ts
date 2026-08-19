/**
 * Runtime configuration.
 *
 * Read through getters rather than module constants so a value picked up from the
 * environment at container start is not frozen into the build output.
 */

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`${name} is not set. Copy .env.example to .env.local and fill it in.`)
  }
  return value
}

export const env = {
  /** Where the dashboard's server side reaches the FastAPI service. Never sent to the browser. */
  get apiBaseUrl(): string {
    return required('API_BASE_URL', process.env.API_BASE_URL ?? 'http://localhost:8000')
  },
  get isProduction(): boolean {
    return process.env.NODE_ENV === 'production'
  },
}
