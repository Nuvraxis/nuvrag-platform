# Frontend workspace

A pnpm + Turborepo workspace holding everything that runs in a browser.

```
apps/
  dashboard/     Next.js 16 tenant dashboard — auth, chatbot CRUD, documents,
                 conversations, embed snippets, analytics, team management
  widget/        dependency-free embeddable chat bundle, served by its own nginx origin
packages/
  api-client/    typed client over the platform API
  types/         types generated from the FastAPI OpenAPI schema
  ui/            shadcn/ui components plus the composites built on them
  config/        shared TypeScript, ESLint and Tailwind theme configuration
```

## Components

`packages/ui/src/components/ui` is vendored shadcn/ui. `components.json` sits in that package,
so add to it from there:

```bash
pnpm --dir packages/ui dlx shadcn@latest add dialog
```

Everything beside that directory is ours and built on top: `EmptyState`, `Stat`, `Spinner`,
and `NativeSelect`.

`NativeSelect` is deliberately not shadcn's `Select`. That one is a Radix listbox which
renders nothing usable until JavaScript has run, and every form here is a Server Action that
submits without it — the control would take the form down with it. Badge and Alert carry two
extra variants, `success` and `warning`, because a document that is still processing is
neither fine nor broken and shadcn's set has no colour for that.

Tokens live in `packages/config/tailwind/theme.css` under shadcn's names, so a freshly added
component is styled the moment it lands. That file also imports `tw-animate-css`, which is
where the `animate-in` / `fade-in-0` / `zoom-in-95` utilities in shadcn's overlay components
come from — without it they are silently no-ops and a dialog snaps into place. Dark mode is the `.dark` class, which nothing sets
yet — adding a toggle is all that is missing.

## Forms

Every form with something to type into is built the way shadcn documents for React Hook
Form: a `Controller` around `Field`, with the label, control, description and message as one
unit. `<FormField>` in the dashboard writes that anatomy once; the control itself comes in as
a render prop, so a field keeps whatever type and autocomplete it needs.

`useActionForm` joins React Hook Form to the Server Action, and the join is the interesting
part. The `action` prop stays on the `<form>` — that is what keeps `useFormStatus` reporting
pending and what lets a browser with no JavaScript post the form at all. An `onSubmit` guard
runs first and, when the values fail the schema, hands the event to `handleSubmit`, which
cancels it on its first line. React honours that and puts the submitter back.

The verdict has to be reached synchronously, which is why the guard calls `safeParse` rather
than awaiting `handleSubmit`: an `await` would land after the event was handled and the
request would already be away.

Two things follow from React Hook Form owning the values. A rejected submit no longer wipes
the form — React resets the uncontrolled inputs of a form it submitted, and these are
controlled — so a form that is meant to be used again, like the invite box, asks for
`resetOnSuccess` instead. And a field the user is repairing clears its message as they type
rather than when they leave, which matters more than it sounds: a message that vanished on
blur would shrink the row at the exact moment the pointer went down on the submit button, and
the click would land on nothing.

One thing `useActionForm` has to undo. React resets a form it submitted through an `action`,
and a controlled `<select>` does not survive that: React marks an option `defaultSelected` only
on the uncontrolled `defaultValue` path, so a reset takes the first option in the list while
React Hook Form still holds the real value — and because React's tree also still holds it, the
next render diffs clean and never puts the DOM right. The control then reads as something the
form is not about to submit. Every `<select>` is restored from the form's values once the
action settles. Controlled `<input>`s need none of this: React keeps their `value` attribute in
step, so the reset restores what was already there.

`src/lib/schemas.ts` mirrors the API's Pydantic models — the same bounds, the same origin
rules. It is a first line, not the line: every action still validates, and a 422 comes back
onto the field that produced it. Where the API names a nested field by its path
(`model_config_json.temperature`) and the form has flattened it, `useActionForm` matches on
the last segment.

Forms with nothing to type into — the row buttons on the team and document tables — have
nothing to validate and stay as plain `<ActionForm>`s.

The **Design** tab is the one form with a second output: `WidgetPreview` renders the widget's
panel from the same custom-property names the widget itself uses, so the values the form
holds and the values the widget will apply are the same values. It is a deliberate copy of
`widget.css`, not an import — the widget ships to other people's sites as its own bundle and
must not grow a dependency on the dashboard — so a layout change there has to be repeated
here, and the preview is only ever a fair impression of the panel.

Resetting that form is its own `<form>` rather than a second button in the first. A reset has
nothing to validate, and sharing the form would let an unfinished colour block the way back
to the default. Its hidden field is `name="intent"`, not `name="reset"`: a form's named
controls shadow its own properties, and `name="reset"` replaces `form.reset` with an input
element, which breaks React's post-action reset and takes the render with it.

`<ConfirmSubmit>` asks before a destructive submit, in shadcn's `AlertDialog`. The button
stays a real submit button and the dialog opens by cancelling its click, which is the whole
trick: with no JavaScript the handler never runs, the click submits as it always did, and
nothing is lost but the question — the API is what actually decides whether the deletion is
allowed. Going ahead calls `requestSubmit` on the button's own form with the button as the
submitter, so the enclosing `ActionForm` runs exactly as it would have.

The **AI provider** tab is the one form with three submitters — save, test chat, test
embeddings — on a single `<form>`, told apart by `name="intent"`. One form rather than three
because all three post the same values, and a test that posted anything other than what a save
would post is a test of nothing.

Which fields each provider needs is a table in `src/lib/ai-providers.ts`, mirroring the API's
`services/ai/registry.py`; `<ProviderSection>` renders whatever the table says, so the
conditional fields are data rather than a branch per provider. The provider lists themselves
come from `@rag/types`, where they are checked against the generated OpenAPI enums at compile
time — that is what keeps Anthropic out of the embedding list without anything here saying so.

Saving is gated on a passing test, and what counts as passing is a *signature*: everything a
test would exercise, serialised, recorded when the test is submitted and compared with the
live form values on each render. Editing a gated field lapses the proof as it is typed. The
gate is an affordance, not the rule — `disabled` renders into the server HTML, so it waits on
`useHydrated()` and a visitor without JavaScript gets a form that posts rather than a dead
button. The API is the authority either way.

Its outcomes toast like everything else, which costs it one thing worth naming: a toast does
not sit beside the section it is about, and this page has two of everything. So the action puts
the half into the message — "Embeddings: could not reach the provider at that address." Field
errors still land on the field and need no such help.

`useFormStatus` returns the `FormData` being submitted alongside `pending`, which is how each
test button knows whether *it* is the one working; the alternative was tracking a submitter in
state or a ref, and both are worse ways of asking a question the submission already answers.

## Reporting mutations

Every Server Action returns an `ActionState`, and `useActionToast` turns it into a sonner
toast: `toast.error` for a rejection, `toast.success` for a save. Small mutations that live in
a table row go through `<ActionForm>`, which owns that wiring so the page around it can stay a
Server Component.

Two deliberate exceptions:

- **One-time values stay on the page.** A new chatbot's secret key and an invitation's accept
  link are shown once and cannot be recovered, so they render in place and suppress the
  success toast rather than scrolling away on a timer.
- **A row that deletes itself does not toast on success.** `revalidatePath` removes the row,
  and with it the component that would have fired the toast — the disappearance is the
  feedback. Errors still toast, because a rejected delete leaves the row where it was.

With JavaScript disabled none of this runs, so every form also renders a `no-js-only` banner
carrying the same message. It is hidden by `@media (scripting: none)`, which needs no inline
script and so cannot trip the CSP.

## Getting started

```bash
pnpm install
cp apps/dashboard/.env.example apps/dashboard/.env.local   # then point API_BASE_URL at the API
pnpm dev
```

`pnpm build`, `pnpm lint`, `pnpm typecheck` and `pnpm format` all run across the workspace
through Turborepo.

## Keeping types in sync with the backend

`packages/types` is generated, not hand-maintained:

```bash
uv run python -m app.tools.export_openapi          # from the repository root
pnpm --filter @rag/types generate
```

Both `openapi.json` and `src/schema.d.ts` are committed, so a contract change shows up as a
reviewable diff and the frontend still builds on a machine with no Python installed.

## How the dashboard talks to the API

Every request is made from the Next.js server, never from the browser. Access and refresh
tokens live in `httpOnly` cookies, which no script on the page can read, and the API's origin
is never exposed to the client at all.

`src/proxy.ts` runs ahead of each request: if the access token has expired it exchanges the
refresh token for a new pair, rewrites the inbound cookie so the page renders with the fresh
token, and sets the new cookies on the response. Pages therefore never see a 401 caused
merely by a token ageing out. It also emits a per-request nonce-based CSP.

Signing out calls the API so the refresh token is actually retired, not merely forgotten
locally.

Mutations are Server Actions. Each form is written so it still works with JavaScript
disabled, and the shared `ActionState` maps the API's 422 payload back onto the field that
produced it — see [Forms](#forms).

`proxy.ts` separates three kinds of route: signed-out-only (`/login`, `/signup`), genuinely
public (`/accept-invitation` — an invitee may already be signed in as someone else, and
bouncing them would strand the link they were sent), and everything else, which requires a
session.

## Notes

- Workspace packages are consumed as TypeScript source and compiled by Next
  (`transpilePackages`), so there is no build step to keep in sync for them.
- Tailwind v4 skips `node_modules` when scanning for classes, so `globals.css` declares
  `@source` for `packages/ui/src` — without it the shared components ship unstyled.
- There is no `loading.tsx` above the chatbot routes on purpose: a streamed fallback commits
  the response headers early, which would turn a cross-tenant 404 into a 200 carrying the
  not-found page.
- A `Suspense` boundary and a visitor with JavaScript disabled do not mix: content streamed
  into a boundary arrives at the end of the document and is moved into place by an inline
  script, so without scripts it stays in the DOM and stays invisible. Measured, not inferred —
  team, settings, documents and design all render their form and hide it. The boundaries are
  kept for the streaming they buy everyone else. The AI provider page is the deliberate
  exception, because there the hidden thing is the only thing on the page.
