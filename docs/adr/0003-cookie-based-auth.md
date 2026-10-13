# 3. Cookie-based auth, token lifetimes and rotation

- Status: Accepted
- Date: 2026-10-13

## Context

The web app on Vercel and the API on its own subdomain need authenticated requests from the browser and from Next.js server components. Tokens stored in `localStorage` are exposed to any XSS. Third-party auth providers add cost and lock-in and do not fit OTP over WhatsApp or the exact session controls we need.

## Decision

Auth is implemented in FastAPI with cookies:

- `__Secure-mo_at`: EdDSA access JWT, 15 minutes, `Domain=.<root>`, HttpOnly, Secure, SameSite=Lax.
- `__Secure-mo_rt`: opaque 256-bit refresh token, stored only as a SHA-256 hash, host-only on the API, `Path=/v1/auth`, SameSite=Strict, 7 days idle and 60 days absolute.
- `__Secure-mo_vt`: verification ticket for first-time OTP, 10 minutes.
- `mo_csrf`: CSRF token bound to the session, readable by JavaScript for the double-submit check.
- `mo_auth`: the access token's expiry as a non-secret hint for proactive refresh.

Every refresh rotates the refresh token. Reusing a rotated token outside a 10-second grace window revokes the whole session family, and revoked families sit in a Redis denylist for 15 minutes. The Next.js server verifies access tokens with the public keys from `/v1/auth/jwks.json`.

## Consequences

- Tokens are never readable by page scripts, which limits the impact of XSS.
- CSRF protection is required on every unsafe method: SameSite cookies, an Origin check and the double-submit token.
- Staging must use a different registrable domain so production cookies never reach it.
- Logout and compromise response are immediate thanks to the denylist, at the cost of one Redis lookup per request.
