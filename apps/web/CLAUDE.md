# apps/web

Rules local to the Next.js frontend. The root `AGENTS.md` and `CLAUDE.md` still apply.

## Layout

- `src/app/` uses route groups: `(public)`, `(auth)`, `(user)` and `(super-admin)`. Only `(public)` has pages so far; `UserShell` and `AdminShell` in `src/components/layouts/` wait for their first pages. Navigation for every area lives in `src/config/navigation.ts`.
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
