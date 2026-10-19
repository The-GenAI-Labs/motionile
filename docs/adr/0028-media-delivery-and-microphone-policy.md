# 28. Media delivery modes and microphone scope

- Status: Accepted
- Date: 2026-10-19
- Refines: [ADR 0010](0010-static-friendly-content-security-policy.md)

## Context

Videos are private. CloudFront serves them from the bucket with signed cookies scoped to the owner's path; deployments without CloudFront (local MinIO, R2, other clouds) need an equivalent. ADR 0010 allowed the microphone for the whole site, but only the voice cloning wizard needs it.

## Decision

- `MediaDelivery` has two implementations chosen by `MEDIA_DELIVERY_MODE`. `cloudfront` issues `CloudFront-Policy`, `CloudFront-Signature` and `CloudFront-Key-Pair-Id` cookies on the shared cookie domain with a custom policy for `https://<cdn>/media/u/<userId>/*`, signed with the RSA key from settings. `presigned` returns per-asset presigned GET URLs from the storage adapter.
- `GET /v1/media/session` refreshes the cookies or reports the mode. The player refreshes before expiry through `use-media-session`.
- Only `media/` is reachable through the CDN. Voice samples, consent recordings, `work/`, `tts/` and `music/` have no CDN behavior.
- The CSP gains `media-src` for the CDN origin and, in presigned mode, the storage origin (`NEXT_PUBLIC_CDN_URL`). The `Permissions-Policy` default is `microphone=()`; a route-specific header for `/settings/voices` sets `microphone=(self)`.

## Consequences

- A cookie for one user cannot fetch another user's path; the policy is the access control.
- Presigned URLs expire, so clients re-request renditions to refresh them; range requests work in both modes.
- The microphone is unavailable everywhere except the voices page.
