# 8. Single dark monochrome theme

- Status: Accepted
- Date: 2026-10-13

## Context

Motionile's product is video. A neutral dark interface keeps attention on the content, and the default video style uses the same palette so the app and its output feel like one product. Supporting multiple themes doubles design and testing work and invites inconsistent colors.

## Decision

- The web app has one dark monochrome theme. There is no light mode, theme toggle or theme provider.
- Colors are defined once as CSS tokens in `apps/web/src/app/globals.css` (`--bg`, `--surface`, `--elevated`, `--border`, `--text-muted`, `--text-secondary`, `--text`, `--accent`, `--ring`, `--danger`, `--success`) and mapped to Tailwind and shadcn/ui variables.
- Components use the mapped utilities only; raw hex values are not allowed in components.
- `color-scheme: dark` is set on the root and the `theme-color` meta tag is `#0E0E10`.
- Fonts are Geist Sans and Geist Mono through `next/font`.

## Consequences

- Visual consistency is cheap to maintain and review.
- Users who prefer a light interface do not get one.
- Accessibility depends on keeping contrast between tokens high, which visual QA checks.
