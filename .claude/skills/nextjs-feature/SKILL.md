---
name: nextjs-feature
description: Patterns for building a Motionile frontend feature with Next.js App Router, React 19, TanStack Query, Zod, react-hook-form, Tailwind v4 brand tokens and shadcn/ui. Use when adding or changing anything under apps/web/src/features or apps/web/src/app.
---

# Next.js feature

## Shape

```
features/<name>/
├── api/<name>.api.ts           Axios calls validated with Zod in and out
├── hooks/use-<thing>.ts        TanStack Query hooks
├── components/                 presentational and leaf client components
├── schemas/<name>.schema.ts    form and view schemas
├── types/<name>.types.ts       types inferred from schemas or the contract
└── query-keys.ts               the only source of query keys
```

## API layer

```ts
import { zGetProjectResponse } from "@motionile/api-contract";

import { apiClient } from "@/lib/api/client";

export const getProject = async (projectId: string) => {
  const response = await apiClient.get(`/v1/projects/${projectId}`);
  return zGetProjectResponse.parse(response.data);
};
```

## Query keys and hooks

```ts
export const projectKeys = {
  all: ["projects"] as const,
  detail: (projectId: string) => [...projectKeys.all, "detail", projectId] as const,
};

export const useProject = (projectId: string) =>
  useQuery({ queryKey: projectKeys.detail(projectId), queryFn: () => getProject(projectId) });
```

## Components

- Server Components fetch on the server; client leaves use hooks.
- Never call Axios from a component. Never build query keys inline.
- No `memo`, `useMemo` or `useCallback` without a profile.
- Forms use `useForm({ resolver: zodResolver(schema) })` and label every field.

## Styling

Use brand utilities only: `bg-background`, `bg-surface`, `bg-elevated`, `border`, `text-foreground`, `text-subtle-foreground`, `text-muted-foreground`, `bg-primary text-primary-foreground`, `ring-ring`, `text-destructive`, `text-success`. No raw hex, no light mode.

## Pages

```ts
export const metadata: Metadata = {
  title: "Pricing",
  description: "Plans and credit packs for Motionile.",
  alternates: { canonical: "/pricing" },
};
```

## Tests

- Vitest and Testing Library, querying by role and accessible name.
- Playwright journeys in `tests/e2e` for new user flows.
