---
name: cybersecurity
description: Explaining information security defensively - the CIA triad, threat modeling, authentication versus authorization, encryption versus hashing, TLS, passwords, multi-factor and passkeys, and how common attack classes (injection, cross-site scripting, CSRF, SSRF, phishing, ransomware, supply-chain compromise, broken access control) work conceptually and how to defend against each. Use for security concepts, secure design and protective practice. Never for attack steps, payloads or tool usage against systems.
metadata:
  layer: domain
---

# Cybersecurity (defensive)

## When to use

Topics about protecting systems, accounts and data, and understanding why attacks succeed so they can be prevented. Audience: developers, IT staff, students and ordinary users. This skill follows `docs/ai-policy.md`: explain an attack class at the level of cause and defense; do not give a procedure someone could follow to compromise a system.

## Structure

1. Name an asset and what must stay true about it (confidentiality, integrity, availability).
2. Name the weakness as a design mistake in plain words (for example "the program trusted input it should have treated as data").
3. Show the trust boundary in a diagram: where untrusted input crosses into something that interprets it.
4. Show the consequence in general terms (data exposed, action taken in the user's name).
5. Spend at least half the video on defenses, in layers: prevent, detect, limit the damage, recover.
6. Close with a short checklist the viewer can act on.

## Analogies and where they break

- Defense in depth as a castle: moat, wall, guard, vault. Breaks: software layers share bugs and can fail together.
- Authentication as showing ID at the door and authorization as which rooms your badge opens. Breaks: authorization must be checked on every request, not only at the door.
- Encryption as a locked box with a key; hashing as a fingerprint. Breaks: encryption is reversible with the key, hashing is not reversible; mixing them up is the misconception to avoid.
- Phishing as a forged letter from your bank. Breaks: the sender can be someone you know whose account was taken over.
- Least privilege as giving a house-sitter only the keys they need. Breaks: permissions accumulate over time unless reviewed.
- Patching as vaccination. Breaks: patches must also be deployed and tested, and protection is not immediate.

## Misconceptions to preempt

- "A padlock or HTTPS means the site is safe." It means the connection is encrypted to that site, not that the site is trustworthy.
- "Hashing and encryption are the same", and "encoding is encryption" (Base64 hides nothing).
- "Complex passwords are best." Length and uniqueness matter more; current NIST guidance (SP 800-63B) favors long passphrases, breached-password checks and no forced periodic rotation. Say "state the guidance edition" if citing.
- "We are too small to be targeted." Most attacks are automated and opportunistic.
- "Security by obscurity is protection." Secrets should be keys, not design.
- "A VPN makes you secure" or "incognito hides you from the network".
- "Antivirus is enough."
- "SMS codes equal passkeys." Phishing-resistant methods (passkeys, hardware keys) beat codes that can be typed into a fake site.

## Terminology

Say vulnerability (a weakness), threat (a source of harm), exploit (a technique that uses a vulnerability), risk (likelihood times impact), attack surface, trust boundary, threat model, least privilege, defense in depth, zero trust, authentication, authorization, session, token, salt, MFA, passkey, TLS, certificate, patch, CVE, incident response, backup, segmentation, logging and monitoring. Say OWASP Top 10 only with its edition year. Avoid "hacker" as shorthand for criminal (use attacker or adversary), "unhackable", "military-grade".

## Defense mapping for the common classes

- Injection: keep data and commands separate with parameterized queries and allow-list validation; least-privilege database accounts.
- Cross-site scripting: encode output for its context, use a content security policy, avoid inserting untrusted text as markup.
- CSRF: SameSite cookies, anti-forgery tokens, check origin on state-changing requests.
- SSRF: allow-list destinations, block internal address ranges, restrict egress.
- Broken access control: enforce authorization on the server per object and per action; deny by default.
- Credential stuffing: unique passwords, MFA, rate limiting, breached-password screening.
- Ransomware: tested offline or immutable backups, patching, segmentation, least privilege.
- Supply chain: pinned and verified dependencies, signed artifacts, software bill of materials, review of new dependencies.

## Visual pairings

- flow-diagram: where untrusted input crosses a boundary, an OAuth or login handshake, TLS handshake summary.
- architecture-build-up: layers of defense added one by one, a threat model of one app.
- comparison-split: vulnerable pattern versus fixed pattern (shown as labeled boxes, not working code), hashing versus encryption.
- timeline-sequence: an incident from detection to recovery.
- concept-metaphor: trust boundaries, least privilege, defense in depth.
- code-walkthrough: only the safe pattern, such as a parameterized query.

## Accuracy checks

- Symmetric encryption uses one shared key; asymmetric uses a key pair. Public keys encrypt or verify; private keys decrypt or sign.
- Passwords are stored as salted hashes from slow functions (argon2id, scrypt, bcrypt), not encrypted and not fast hashes alone.
- 401 and 403 differ; do not conflate authentication with authorization failures.
- State protocol versions when it matters (for example TLS 1.2 versus 1.3).
- Any statistic about breaches needs a source and year, or leave it out.

## Do

- Use fictional organizations, fake data and defanged examples.
- Describe defenses concretely enough to act on.
- Label severity honestly; do not use fear.

## Don't

- Don't show working exploit strings, payloads, commands, scan or attack tool usage, or how to evade detection.
- Don't describe how to build malware, steal credentials or bypass a named product's protections.
- Don't name real victims or real incident details beyond public, well-documented history.
