# 15. OTP-based password reset

- Status: Accepted
- Date: 2026-10-15
- Supersedes: the thirty-minute emailed password-reset token in context section 7

## Decision

Reset uses the same OtpService as contact verification, OTP login and first-password setup. A six-digit code is generated with secrets, stored only as an HMAC of purpose, destination and code, expires after five minutes and permits five attempts. Redis transactions make verification and consumption atomic. A host-only HttpOnly verification-ticket cookie references the challenge and purpose for ten minutes; no ticket or code enters a URL.

Forgot-password always returns a masked challenge shape, including for absent and unavailable accounts. A successful reset changes the argon2id credential, revokes all session families, updates the access denylist and queues a security notice. Authenticated password change retains the current family; adding the first password requires an OTP bound to the signed-in user.

## Consequences

Phone-only accounts can recover through WhatsApp. Resend and destination limits apply consistently across purposes. Lost or expired challenges require another request, and the frontend in Phase 5 must preserve the ticket cookie.
