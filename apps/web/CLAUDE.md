# apps/web

Rules local to the Next.js frontend. The root `AGENTS.md` and `CLAUDE.md` still apply.

## Layout

- `src/app/` uses route groups: `(public)`, `(auth)`, `(user)` and `(super-admin)`. Auth pages are static; user and admin layouts verify the session dynamically. Navigation for every area lives in `src/config/navigation.ts`.
- `src/lib/api/` holds the browser Axios client, `ApiError` and the server-only `serverFetch`; `src/lib/query/` holds the TanStack Query client factories; `src/lib/seo/` holds `buildMetadata()` and the JSON-LD builders.
- `src/components/shared/` holds page header, empty state, spinner, confirm dialog, virtualized data table, cursor pagination and permission gate.
- `src/config/security-headers.ts` builds the CSP and security headers; see ADR 0010 before adding an origin.
- `src/components/ui/` holds shadcn/ui primitives. Add new ones with `pnpm dlx shadcn@latest add <name>` and then remove any comments the generator writes.
- `src/features/<feature>/` follows `api/<feature>.api.ts`, `components/`, `hooks/`, `schemas/<feature>.schema.ts`, `types/<feature>.types.ts`, `query-keys.ts`.
- `src/config/` holds `env-schema.ts` (Zod validation), `env.ts` (validated values) and `site.ts` (brand constants).
- `tests/unit/` holds Vitest and Testing Library tests.

## Commands

Run from the repository root:

| Command                                  | Purpose                                           |
| ---------------------------------------- | ------------------------------------------------- |
| `pnpm --filter @motionile/web dev`       | Dev server on port 3000 (uses `.env.development`) |
| `pnpm --filter @motionile/web build`     | Production build; requires `NEXT_PUBLIC_SITE_URL` |
| `pnpm --filter @motionile/web lint`      | ESLint with the Next.js preset                    |
| `pnpm --filter @motionile/web typecheck` | Route type generation and `tsc`                   |
| `pnpm --filter @motionile/web test:unit` | Vitest with coverage                              |

## Rules

- Style only with Tailwind utilities mapped to the brand tokens (`bg-background`, `bg-surface`, `text-muted-foreground`, `text-subtle-foreground`, `border`, `ring-ring`). Never use raw hex values or arbitrary colors.
- Add a new public environment variable in three places: `src/config/env-schema.ts`, `src/types/env.d.ts` and the root `.env.example`. Reference it as `process.env.NEXT_PUBLIC_*` so Next.js inlines it.
- Export `metadata` from every page through `buildMetadata()` with a unique description and canonical path.
- Normalize every API failure into `ApiError`; components never read Axios errors directly.
- Set `NEXT_PUBLIC_API_URL` in every deployed environment; it defaults to `http://localhost:8000` and feeds both the Axios base URL and `connect-src`. `API_INTERNAL_URL` is optional and server-only.
- The legal pages are drafts pending the owner's legal review; keep the visible draft notice until they are approved.
- Prefer Server Components. Client components are leaves that need state, effects or browser APIs.
- Import the API contract from `@motionile/api-contract`; never hand-write API types.
- Every component test asserts through accessible roles and names, not class names.

## Billing and credits

- `features/billing` and `features/credits` follow the standard feature shape. Money is integer paise; format it only for display with `formatPaise` in `src/lib/utils/format.ts` and show "incl. GST" wherever a price appears. Never hold money as a float.
- Creating an order or subscription sends an `Idempotency-Key` that `useCheckout` generates when the user clicks and reuses for retries of that click. Verification keys are `verify:<razorpayPaymentId>`.
- `lib/razorpay` loads Checkout lazily and once (`load-checkout.ts`). `checkout-launcher.tsx` loads the real checkout with `next/dynamic` and, only when `NEXT_PUBLIC_PROVIDERS_MODE=fake`, the simulated one that calls the API's `/v1/_test/razorpay` routes. The checkout never settles a payment: the success handler verifies, then always navigates to `/billing/status/[orderId]`, which polls the order until the webhook or verification settles it.
- `NEXT_PUBLIC_PROVIDERS_MODE` is `live` unless set. `fake` is rejected unless `NEXT_PUBLIC_SITE_URL` is a local address, so CI can serve a production build with fake providers and a deployed build cannot.
- The pricing page is static: it fetches `GET /v1/billing/products` with the `billing-products` tag and a five-minute revalidate. `/api/revalidate` only accepts `billing-products` and `catalog` tags. A failed fetch while building renders the page without products; a failed revalidation keeps the last good page.
- The Razorpay theme colour comes from `siteConfig.themeColor`. It is the only place a hex value reaches Razorpay.

## Authentication

- Auth API calls use generated writable request schemas so password fields remain present. Challenge UI metadata lives in a per-tab Zustand store; verification tickets remain HttpOnly cookies.
- `lib/auth` owns JWT server verification, guards, safe destinations, refresh coordination and cross-tab events. Mount `SessionKeepalive` once per protected shell.
- `NEXT_PUBLIC_SITE_URL` is the web origin; `NEXT_PUBLIC_API_URL` is the browser API origin. `NEXT_PUBLIC_JWKS_URL` optionally overrides the API JWKS endpoint for server verification. `AUTH_JWT_ISSUER` and `AUTH_JWT_AUDIENCE` must match the API. Never put signing keys in the web environment.
- Set `NEXT_PUBLIC_TURNSTILE_SITE_KEY` explicitly when deployed. Local and CI use Cloudflare's dummy site key.
- Local `AUTH_COOKIE_DOMAIN` is empty. Host-only localhost cookies are shared between ports 3000 and 8000; cookies do not isolate ports. All auth cookies remain Secure, so browser auth uses HTTPS, including the CI reverse proxy at https://localhost:3443.
- OAuth sign-in uses the API GET start URL. Linking uses the CSRF-protected POST start endpoint, then navigates to its validated URL.

## Media and voices

- `features/library` owns playback: `RenderPlayer` (data-aware, takes `renderId`) wraps `VideoPlayer` (presentational, takes `renditions` and `deliveryMode`), which loads through `next/dynamic` in `lazy-video-player.tsx`. Hooks are `useRender`, `useRenditions` and `useMediaSession`; never call the render or media endpoints from components.
- `useMediaSession` shares one TanStack Query across players. In `cloudfront` mode it refreshes the signed cookies about 60 seconds before `expiresAt` while the tab is visible, re-checks when the tab becomes visible again, and adopts a newer session another tab recorded in `localStorage` under a Web Lock. In `presigned` mode it only exposes the mode; `useRenditions` re-fetches the list before the earliest presigned URL expires. `refresh()` forces a renewal and is what the player calls after a playback error.
- `SHARE_INTERNAL_SECRET` is server only (never `NEXT_PUBLIC_`, read in `share.server.api.ts`, not in `env-schema.ts`): `loadSharedVideo` sends it as `X-Motionile-Internal` so the API neither rate-limits nor counts the Vercel server as a visitor, and production throws when it is missing. The browser counts the view once on first `play` through `useRecordShareView`, which posts to `/v1/share/<slug>/views` and ignores failures (ADR 0037).
- `VideoPlayer` sets `crossOrigin="use-credentials"` in `cloudfront` mode and `anonymous` otherwise, never autoplays, keeps the position when the aspect changes, and applies refreshed presigned URLs only while paused or after an error.
- `NEXT_PUBLIC_MEDIA_ORIGIN` is the storage origin for presigned media, posters and admin music previews. Together with `NEXT_PUBLIC_CDN_URL` it feeds `media-src` and `img-src`. Text tracks are covered by `media-src`; do not widen `connect-src` for media. `media-src` also allows `blob:` (and only `media-src`) so the cloning wizard can play back a recording; `tests/unit/security-headers.test.ts` fails if `blob:` appears in any other directive.
- The global `Permissions-Policy` is `microphone=()`. Only `/settings/voices` and its nested paths send `microphone=(self)`, through the second rule in `buildHeaderRules`. Never allow the microphone anywhere else; `tests/unit/security-headers.test.ts` enforces it.
- `features/admin-music` backs `/admin/music` (permission `music.manage`): cursor-paginated table, upload and edit dialogs, confirmed activate and deactivate, and an inline preview from the presigned `previewUrl`. Problem codes map to guidance in `errors.ts`.
- Reusable filter controls live in `components/shared/filter-fields.tsx`.
- `features/admin-render` backs `/admin/render` and `/admin/render/[renderId]` (permission `render.testbed`). `extractScenes` reads `[data-scene]` values with `DOMParser`; `buildTestbedForm` sends the `composition` file, the `options` JSON string and one audio part per scene named `audio-<index>` (the `audioPart` in the options). Creating a render, golden or uploaded, navigates to the render page. The page loads the render once, then `useRenderEvents` follows `GET .../events` with `fetch` and the session cookie (`sse.ts` parses frames by hand; the generation job page uses `@microsoft/fetch-event-source`), reconnecting with exponential backoff and refreshing the session on a 401. After four consecutive failures `connection` becomes `polling` and `useTestbedRender` re-fetches the render every three seconds. The terminal event invalidates the render query, which supplies the validation report, stage timings and renditions; completed renders play through `RenderPlayer`. Failure codes map to guidance in `errors.ts`.
- `features/voices` backs `/settings/voices` and `/settings/voices/new`. The gallery lists built-in and cloned voices through one `useAllVoices` query that loads every page and polls every four seconds while a clone is `pending`; one hidden `<audio>` element plays one presigned preview at a time (`useVoicePreviewPlayer`). Setting or clearing the default voice goes through `useDefaultVoice`, which sends the full preferences update with the new `defaultVoiceId`; any other preferences update must also send `defaultVoiceId` or the default is cleared.
- The cloning wizard (`clone-wizard.tsx`, loaded with `next/dynamic`) keeps its steps, consent clip and upload list in the per-tab Zustand store `clone-wizard.store.ts`; the attempt and its samples stay in TanStack Query. The consent statement and version come from the public setting keys `voices.consent_statement` and `voices.consent_statement_version`; `POST /v1/voices/clones` sends that version and its response is authoritative. Recordings are `Blob`s that only leave the browser through the upload requests. `useAudioRecorder` feature-detects `MediaRecorder`, exposes an `AnalyserNode` level for the `role="meter"`, enforces the maximum length and stops every track and the `AudioContext` on stop and on unmount. Submitting reuses one `Idempotency-Key` per click for retryable failures (`useCloneSubmit`).
- `features/admin-voices` backs `/admin/voices` (permission `voices.manage`): built-in catalog table with status and language filters, sync with added and unchanged counts, an edit dialog with a tag input and an expose switch (exposing generates the preview), and regenerate preview. Inline playback uses the user preview endpoint, so only exposed (`ready`) voices with a preview can be played.
