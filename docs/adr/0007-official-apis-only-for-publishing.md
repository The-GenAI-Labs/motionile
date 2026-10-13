# 7. Official APIs only for publishing

- Status: Accepted
- Date: 2026-10-13

## Context

Users want to publish videos to many platforms in one click. Some platforms have no public posting API. Automating a user's account through a headless browser breaks platform terms, risks account bans, needs stored passwords and fails unpredictably.

## Decision

- Publishing uses only official platform APIs: YouTube, LinkedIn, Instagram Reels, Facebook Pages, Threads, X, TikTok, Dev.to, Hashnode, WordPress, Ghost and Blogger.
- Platforms without an API, such as Medium and Substack, get a share kit: format downloads, a copyable caption, composer links and the native mobile share sheet.
- Stealth or headless-browser automation of user accounts is never used.
- Each platform is a `PublisherProvider` with `connect`, `refresh`, `validate`, `upload`, `publish` and `fetch_status`. Credentials are AES-GCM encrypted with a versioned key.

## Consequences

- Publishing is reliable, compliant and revocable by the user.
- Some platforms need app review before launch, which is why developer applications are submitted in Phase 3.
- Platforms without APIs get a manual but guided flow.
