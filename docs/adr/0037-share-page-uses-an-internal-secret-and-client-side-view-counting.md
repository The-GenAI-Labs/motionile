# 37. The share page uses an internal secret and client-side view counting

- Status: Accepted
- Date: 2026-10-29

## Context

`GET /v1/share/{slug}` is public and is called by the Next.js server, not by the visitor's browser (`features/library/api/share.server.api.ts` through `serverFetch`). The API therefore sees the egress address of the web host for every visitor. Two controls keyed on the client address then apply to all visitors together: the `share.view` limit (120 per minute per IP) and the once-per-IP-per-hour view dedupe. A scraper that opens enough share pages exhausts the limit for every share page, and view counts collapse to one per hour per link.

The API trusts forwarded address headers only from its own reverse proxy, so the web host cannot tell the API who the visitor is by sending `X-Forwarded-For`.

## Decision

- The web server authenticates itself with a shared secret. `SHARE_INTERNAL_SECRET` (`ShareSettings.internal_secret`, at least 32 characters, required by `Settings.deployment_problems()` for the service role) is sent by `loadSharedVideo` as the header `X-Motionile-Internal`. The API compares it with `hmac.compare_digest` over SHA-256 digests of both values, so the comparison takes the same time for every input length.
- A request with a valid header skips the per-IP limiter and does not count a view. A request with an absent or invalid header behaves as before: limited per IP and counted at most once per IP per hour. The endpoint stays usable directly and the secret grants nothing else.
- Views are counted by the visitor's browser. `POST /v1/share/{slug}/views` (`share_record_share_view`, 204, public) is called once when playback first starts. It is limited by the new policy `share.count` (60 per minute per IP), returns the same constant 404 as the read for unknown, revoked and expired links, and shares the Redis dedupe key of the read, so a direct read and a counted view from the same address still count once per hour.
- The endpoint needs no CSRF token because it changes only a counter and reads no cookies. It follows the other public unsafe endpoints: no `enforce_csrf`, and the origin guard still rejects requests from origins outside `CORS_ALLOWED_ORIGINS`.
- The web reads the secret from the server-only environment variable `SHARE_INTERNAL_SECRET`. In production a missing value throws when a share page loads; in other environments it logs an error and calls the API without the header.

## Alternatives considered

- **Trust forwarded address headers from the web host.** Rejected: it would make the API accept client-controlled `X-Forwarded-For` from any caller that can reach it, which defeats the rule that only the API's own reverse proxy is trusted, and every attacker could then pick a fresh address per request.
- **An HMAC-signed visitor address.** The web server would forward the visitor's address with a signature. Rejected: the web server would have to trust a forwarded header to learn that address, the signature adds key distribution and replay questions that a shared secret already answers, and it would still count a view for every server render, including crawlers and link previews that never play the video.
- **Keep counting on the read and raise the limit.** Rejected: a higher shared limit only moves the point where one scraper locks everyone out, and view counts would still be one per hour per link.

## Consequences

- Share pages no longer depend on a shared egress address: scrapers are limited by their own address when they call the API directly, and by the web host's own protections when they call the page.
- A view now means that someone pressed play. Page loads that never play, crawlers and link-preview fetchers are not counted.
- Anyone who learns the secret can read share pages without the per-IP limit. It is an `owner` secret in `deploy/parameters.csv`; rotate it in the API parameter store and in the web environment together; there is no overlap window, so a rotation briefly makes production share pages fail until both sides carry the new value.
- Counting from the browser can be called by anyone with a valid slug, at most 60 times a minute per address and once per hour per address and link. A determined visitor can inflate a count by rotating addresses, as before.
- The contract gains `share_record_share_view`; the generated client and the Zod schemas include it.
