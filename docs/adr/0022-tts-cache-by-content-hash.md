# 22. TTS cache keyed by content hash

- Status: Accepted
- Date: 2026-10-19

## Context

Narration is paid per character. Repairs, retries, resumed renders, test-bed runs of the same golden composition and repeated sentences all synthesize the same text with the same voice. Paying twice for identical audio wastes money and time, and word timestamps from two syntheses of the same text differ slightly, which would break frame-identical output between runs.

## Decision

- Every synthesis goes through `tts_cache`. The key is a SHA-256 over the provider, the model, the provider voice ID, the normalized text and the synthesis settings (speed, stability, language, output format), each length-prefixed.
- Text is normalized by Unicode NFC, collapsing whitespace and trimming; case and punctuation are kept because they change prosody.
- An entry stores the audio asset (a system asset under `tts/`), the word timings, the duration, the billed characters and a last-used time. A hit returns the stored audio and timings and writes no usage row.
- The cache is global: the key includes the voice, so built-in voices share entries across users, and a cloned voice's entries are only reachable by someone who can select that voice. Deleting a cloned voice deletes its entries and audio at once.
- Concurrent identical requests race on the unique hash; the loser discards its result and reads the winner's entry.
- Entries unused for 90 days are pruned by `media.prune_tts_cache`.
- `tts/` is never served by the CDN. Only `media/` is.

## Consequences

- Identical narration is synthesized and paid for once, and a resumed or repeated render reproduces its timings exactly.
- A change of provider, model, voice, text or settings is a different key, so stale audio is never returned.
- The cache holds audio of cloned voices; the deletion rule above is part of the voice deletion contract.
