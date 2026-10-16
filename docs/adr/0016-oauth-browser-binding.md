# 16. Bind OAuth callbacks to the initiating browser

- Status: Accepted
- Date: 2026-10-15
- Refines: ADR 0003

## Decision

OAuth uses an additional host-only cookie, __Secure-mo_oauth, with HttpOnly, Secure, SameSite=Lax, Path=/v1/auth and a ten-minute lifetime. Redis state contains its SHA-256 binding, provider, PKCE verifier, nonce, validated relative next path, intent and linking principal. State is consumed atomically once and its browser binding is compared in constant time. Linking also requires the same authenticated family on callback and CSRF on start.

## Consequences

The Strict verification ticket cannot accompany an external provider's top-level callback. A separate Lax cookie supports that callback without relaxing OTP or refresh cookies. This prevents login CSRF through attacker-generated authorization states. Callback URLs always use the configured web origin and validated relative paths. Provider failures redirect to a fixed login error URL.

Browser account linking uses a CSRF-protected POST start endpoint returning the authorization URL, because a navigation link cannot attach the required CSRF header. GET start retains the redirect flow for provider sign-in.
