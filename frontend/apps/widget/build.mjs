/**
 * Produces the immutable, content-hashed widget bundle plus the small stable loader.
 *
 * Hashed filenames are what let nginx serve the bundle with a one-year immutable cache while
 * a rollout still propagates instantly: the loader (short cache) simply starts pointing at a
 * new hash. Subresource Integrity is emitted alongside so a tampered CDN object is rejected
 * by the browser rather than executed.
 */
import { createHash } from 'node:crypto'
import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const srcDir = join(root, 'src')
const outDir = join(root, 'dist')

const contentHash = (buffer) => createHash('sha256').update(buffer).digest('hex').slice(0, 10)
const integrity = (buffer) => `sha384-${createHash('sha384').update(buffer).digest('base64')}`

async function emit(name, extension) {
  const source = await readFile(join(srcDir, `${name}.${extension}`))
  const filename = `${name}-${contentHash(source)}.${extension}`
  await writeFile(join(outDir, filename), source)
  return { filename, integrity: integrity(source), bytes: source.length }
}

await rm(outDir, { recursive: true, force: true })
await mkdir(outDir, { recursive: true })

const style = await emit('widget', 'css')
const script = await emit('widget', 'js')

const frame = (await readFile(join(srcDir, 'frame.html'), 'utf8'))
  .replaceAll('__STYLE__', style.filename)
  .replaceAll('__STYLE_INTEGRITY__', style.integrity)
  .replaceAll('__SCRIPT__', script.filename)
  .replaceAll('__SCRIPT_INTEGRITY__', script.integrity)

await writeFile(join(outDir, 'frame.html'), frame)

// loader.js keeps its name forever — it is the URL baked into every tenant's HTML.
await cp(join(srcDir, 'loader.js'), join(outDir, 'loader.js'))

const manifest = {
  version: script.filename.split('-')[1].split('.')[0],
  entry: 'frame.html',
  assets: {
    script: { file: script.filename, integrity: script.integrity },
    style: { file: style.filename, integrity: style.integrity },
  },
}
await writeFile(join(outDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`)

// Where the API lives is a deployment fact, not a build one, so this file is meant to be
// replaced at deploy time — the Helm chart mounts its own over it. The default is what a
// local compose stack uses, which keeps `pnpm dev` working with no extra wiring.
const config = { apiBase: process.env.WIDGET_API_BASE || 'http://localhost:8000' }
await writeFile(join(outDir, 'config.json'), `${JSON.stringify(config, null, 2)}\n`)

const total = style.bytes + script.bytes + Buffer.byteLength(frame)
console.log(`widget build -> dist/ (${(total / 1024).toFixed(1)} KB uncompressed)`)
console.log(
  `  ${script.filename}\n  ${style.filename}\n  frame.html\n  loader.js\n  manifest.json\n  config.json`,
)
