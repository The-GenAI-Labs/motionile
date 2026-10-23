# 27. Voice consent verification

- Status: Accepted
- Date: 2026-10-19

## Context

Cloning a voice from audio makes it possible to impersonate someone. The product must only clone a voice for the person who is speaking in the samples, with a record that stands up to a misuse report.

## Decision

1. The user reads and accepts a versioned consent statement. The text and version live in runtime settings; the accepted text's SHA-256 is stored with the consent.
2. The API generates a random consent sentence for this attempt (a fixed phrase plus random words and digits) and keeps it, with the attempt, in Redis for one hour. Replaying an old recording fails because the sentence is new.
3. In the browser the user records themselves reading the sentence, plus 30 seconds to 5 minutes of samples, recorded or uploaded.
4. Every file is validated with ffprobe for a real audio container, an audio stream and no video stream, plus size and duration limits, then transcoded by ffmpeg to a standard mono WAV. Only the transcoded file is stored; the upload is discarded, so a polyglot never persists.
5. The consent recording is transcribed by a speech-to-text provider. The transcript must match the sentence within a tolerance (normalized word similarity of at least 85%). A mismatch fails the clone with `consent_mismatch`.
6. Only then is the voice created at the provider (instant voice cloning) and a preview generated. Cloning can cost credits through the credits reservation flow (runtime setting; default 0) and is limited per user (runtime setting).
7. A `voice_consents` row records the statement version and hash, time, IP, user agent, the consent recording, the sentence, the transcript, the match and the sample counts. The row outlives the voice for the period in `retention.md`.

Deleting a cloned voice deletes it at the provider, deletes its samples and preview from storage and removes its TTS cache entries. A user purge deletes all of a user's voices the same way. Admin sync and curation apply to built-in voices only; no admin can clone.

## Consequences

- A voice exists only if a live reading of a fresh sentence matched; recordings cannot be reused across attempts.
- The API image needs ffmpeg for validation; it runs with strict arguments, a timeout and size limits, and never keeps the upload.
- Consent evidence is kept after deletion, so the retention rule is part of the product's privacy notice.
