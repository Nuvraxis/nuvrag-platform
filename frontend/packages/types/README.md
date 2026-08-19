# @rag/types

TypeScript types for the platform API, generated from FastAPI's OpenAPI schema so the
frontend contract cannot drift from the backend without failing a build.

## Regenerating

`openapi.json` is exported from the application rather than scraped from a running server,
so this works in CI without Postgres or Redis:

```bash
# from the repository root
uv run python -m app.tools.export_openapi
pnpm --dir frontend --filter @rag/types generate
```

Both `openapi.json` and `src/schema.d.ts` are committed. That keeps `pnpm build` working on
a machine with no Python toolchain, and makes a backend contract change visible in review as
a diff rather than as a silent regeneration.

`src/index.ts` is hand-written: it names the generated types the way the UI refers to them
and restates the paginated envelope, which OpenAPI emits once per concrete item type.
