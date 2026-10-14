# 10. Static-friendly Content Security Policy

- Status: Accepted
- Date: 2026-10-13

## Context

Public pages are statically rendered for speed and SEO. Next.js inlines small bootstrap scripts (`self.__next_f.push(...)`) into every page. A nonce-based CSP needs a fresh nonce per response, which forces dynamic rendering of every page and removes static caching. Hashes do not work either, because the inline payloads change with every build and Next.js subresource integrity only covers external chunks. Later phases need Cloudflare Turnstile, Razorpay Checkout, an API on another origin and media from a CDN.

## Decision

`apps/web/src/config/security-headers.ts` builds one policy for every route, applied from `next.config.ts`:

- `default-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`, `font-src 'self'`.
- `script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com https://checkout.razorpay.com`. No nonce, hash or `'strict-dynamic'` is listed, so `'unsafe-inline'` takes effect for the Next.js bootstrap scripts.
- `'unsafe-eval'` only in development, for React Refresh and error overlays. A unit test fails if it appears in the production policy.
- `style-src 'self' 'unsafe-inline'` for inline style attributes from Radix positioning, virtualized rows and toasts.
- `connect-src 'self'`, the API origin (`NEXT_PUBLIC_API_URL`) and `https://api.razorpay.com`.
- `img-src 'self' data:` and `media-src 'self'`, plus the CDN origin when `NEXT_PUBLIC_CDN_URL` is set.
- `frame-src https://challenges.cloudflare.com https://api.razorpay.com https://checkout.razorpay.com`.
- `upgrade-insecure-requests` and HSTS only outside development, and `upgrade-insecure-requests` only when the site URL is https, so local and CI production builds on `http://localhost` keep working.
- `Referrer-Policy: strict-origin-when-cross-origin`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and a `Permissions-Policy` that disables unused features, allows the microphone for our own origin (voice samples) and payment for Razorpay. No `X-Powered-By`.
- `Cross-Origin-Opener-Policy` is not set, because Razorpay Checkout relies on `window.opener` in its popup flow.

## Consequences

- Public pages stay static and cacheable.
- Inline script injection is not blocked by CSP. Defence relies on React escaping, no `dangerouslySetInnerHTML` except the escaped JSON-LD serializer, strict input validation, and the restricted script origins, `object-src`, `base-uri` and `frame-ancestors`.
- When authenticated, dynamically rendered areas arrive, they can move to a per-request nonce with `'strict-dynamic'` in `proxy.ts` while public pages keep this policy. That change needs a new ADR.
- Adding a third-party origin means editing `security-headers.ts` and its tests, which keeps every exception reviewed.
