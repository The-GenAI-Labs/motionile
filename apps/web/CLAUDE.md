# apps/web

Rules local to the Next.js frontend. The root `AGENTS.md` and `CLAUDE.md` still apply.

## Layout

- `src/app/` uses route groups: `(public)`, `(auth)`, `(user)` and `(super-admin)`. Only `(public)` exists in Phase 1.
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
- Export `metadata` from every page with a unique description and canonical URL.
- Prefer Server Components. Client components are leaves that need state, effects or browser APIs.
- Import the API contract from `@motionile/api-contract`; never hand-write API types.
- Every component test asserts through accessible roles and names, not class names.
