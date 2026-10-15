# 14. Transactional email and WhatsApp delivery

- Status: Accepted
- Date: 2026-10-15

## Decision

The notifications module owns email and WhatsApp delivery behind sender protocols. It owns no tables. Email uses SES API v2 through the instance role in deployed environments, SMTP with Mailpit locally, and a recording fake in tests. WhatsApp uses approved authentication and security utility templates through SafeHttpClient restricted to graph.facebook.com.

Jinja2 renders escaped HTML and plain text with a Motionile signature. Requests enqueue encrypted notification payloads after database commit on the default procrastinate queue. OTP jobs have priority 10; other notices have priority 0. Tasks retry five times. Payload encryption prevents queue inspection and task failure output from exposing codes and destinations. Encryption keys must remain available until pending jobs finish.

## Consequences

SES joins storage as an explicitly allowed AWS SDK adapter. Sending is asynchronous and retries may duplicate delivery, so messages explain their expiry. The existing after-commit helper logs enqueue failures; it does not provide a durable outbox across a crash between commit and enqueue. Operators must alert on db.after_commit_failed and users can resend after cooldown. A transactional outbox is a separate reliability refinement, not claimed by this implementation.

Fake messages are retained for one hour in Redis, limited to twenty per destination. The inbox route is mounted only in local and CI and refuses live provider mode. Approved Meta security utility templates are required for phone-only accounts to receive security notices.
