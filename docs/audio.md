# Audio engine

Narration, mixing, loudness, subtitles and voices. The render pipeline that consumes them is in [`render.md`](render.md). Code lives in `apps/server/src/motionile/engine/audio` (providers, alignment, assembly, mixing, subtitles) and in the `media` and `voices` modules (cache, usage, orchestration, HTTP).

Decisions: [ADR 0022](adr/0022-tts-cache-by-content-hash.md) (TTS cache), [0023](adr/0023-music-library-and-licensing.md) (music), [0027](adr/0027-voice-consent-verification.md) (voice consent).

## 1. Text-to-speech providers

`engine/audio/providers/base.py` defines the interfaces. The engine never imports a module: the cache, the usage log and the voice records are reached through ports that `modules/media` implements.

```python
class TTSProvider(Protocol):
    name: str
    model: str
    returns_native_timestamps: bool

    async def synthesize(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> SynthesisResult: ...
```

- `VoiceRef` is the provider and the provider voice ID. `SynthesisOptions` carries language, speed, stability and output format. `SynthesisResult` is the audio bytes with their content type, the duration in milliseconds, the word timings (`text`, `start_ms`, `end_ms` per word, relative to the audio start), the billed characters, the cost in micro-dollars and the model.
- `model` is part of the cache key, so a provider exposes the model it is configured with. The duration is measured by decoding the audio with ffmpeg, never taken from the provider (ffprobe cannot read the duration of an MP3, WAV or Opus stream piped to it). Word timings are clamped to it and made monotonic (each word starts at or after the previous word ends).

| Provider     | Timestamps                                                                                                                  | Notes                                                                                                                                                                      |
| ------------ | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `elevenlabs` | Native. Uses `POST /v1/text-to-speech/{voice_id}/with-timestamps`, which returns base64 audio and a per-character alignment | Character alignment is converted to words: the text is split on whitespace, each word starts at its first character's start time and ends at its last character's end time |
| `openai`     | None. `POST /v1/audio/speech` returns audio only                                                                            | An `Aligner` derives word timings from a word-level transcription of the generated audio                                                                                   |
| `fake`       | Synthetic                                                                                                                   | Deterministic tone (or silence) whose length follows the text, with plausible per-word timings; used whenever `PROVIDERS_MODE=fake`                                        |

All outbound calls go through `SafeHttpClient`. API keys are `SecretStr` settings (`ELEVENLABS_API_KEY`, `OPENAI_API_KEY`) and never reach logs.

### 1.1 Alignment

`Aligner.align(audio, text, language, *, filename, duration_ms)` runs a `Transcriber` (word-level transcription) and maps the source words onto the transcribed words with a sequence match. Source words with no counterpart (numbers, punctuation, abbreviations that the transcript spells differently) get timings interpolated between their matched neighbors. Words with no transcribed counterpart in the gap use the span of the transcribed words that sit there, or the silence between their matched neighbors. The result always has exactly one timing per source word, in order, inside the audio duration.

Transcribers: ElevenLabs speech-to-text (`scribe_v1`), OpenAI `whisper-1` with word timestamp granularity, and a fake that derives words from the audio length. `AUDIO_TRANSCRIBER` selects one. The same interface transcribes the consent recording of a voice clone.

## 2. Caching and usage

Every synthesis goes through `tts_cache`:

- **Key:** SHA-256 over length-prefixed provider, model, provider voice ID, normalized text (NFC, whitespace collapsed and trimmed) and the synthesis settings.
- **Hit:** the stored audio and word timings are returned; nothing is synthesized, no usage row is written and `hit_count` and `last_used_at` are updated.
- **Miss:** the provider is called, the audio is stored as a system asset under `tts/`, the entry is inserted, and one `usage_records` row is written through `motionile.modules.credits.record_usage`: stage `tts`, the provider, the model, the characters, the cost in micro-dollars and zero credits. The engine draws one nonce before it calls the provider and records the usage immediately after the call and before `tts_cache` stores the audio, with the idempotency key `tts:<cache-key-hex>:<nonce>`; a failure after a billed call therefore never loses the row, a retry that misses the cache is a new paid call with its own nonce, and recording the same nonce twice is a no-op. `SpeechService.synthesize_text` takes an optional `job_id` that is stored in `usage_records.job_id` so a render can attribute its narration.
- **Race:** concurrent identical requests insert the same hash; the loser reads the winner's entry. Both syntheses were paid for and both write a usage row.
- A cloned voice's entries are deleted with the voice. Entries unused for 90 days are pruned by `media.prune_tts_cache`.

## 3. Narration assembly

`engine/audio/narration.py`:

1. One synthesis per scene (or the scene's uploaded audio, probed with ffprobe).
2. Each scene's audio is normalized to 48 kHz mono 16-bit WAV.
3. `RENDER_SCENE_PADDING_MS` of silence follows every scene except the last. A scene's duration is its audio plus that padding.
4. The result is the object injected as `window.__narration`: per scene its start, duration, text and words with absolute and scene-relative millisecond timings ([`render.md`](render.md) section 4).

`MediaService.narrate(...)` exposes this step on its own so Phase 9 can synthesize narration, hand the durations to the generator, and render later: the cache returns identical audio and timings on the second call.

## 4. Mixing

`engine/audio/mix.py` builds the filter graph with ffmpeg:

1. Concatenate the scene audio, with the padding, into the voice track; pad with silence to the video length including the tail.
2. Optional music from `music_tracks` (active tracks only): looped or trimmed to the length, lowered, faded in over 1 second and out over the tail, and **ducked under the voice** with `sidechaincompress` keyed by the voice track.
3. Mix voice and music to stereo.
4. **Loudness, two passes:** pass 1 runs `loudnorm` in measurement mode (`I=-16`, `TP=-1.5`, `LRA=11`) and reads the JSON; pass 2 applies the measured values with `linear=true`.
5. Encode AAC at 48 kHz.

Targets: −16 LUFS integrated, −1.5 dBTP true-peak ceiling. The integration suite measures the encoded result with `ebur128` and accepts integrated loudness within ±1 LU of the target and a true peak not above −1.0 dBTP (the AAC encoder can overshoot the filter's ceiling slightly).

Music is validated at upload (ffprobe: real audio, one audio stream, duration limits) and transcoded to AAC in an `.m4a` at 48 kHz stereo before it is stored under `music/`.

## 5. Subtitles

`engine/audio/subtitles.py` builds cues from the word timings and renders three formats.

**Segmentation rules**

- At most 2 lines of 42 characters per cue; lines are balanced.
- A cue lasts at least 1.0 second (extended into the gap before the next cue, never past it) and at most 6.0 seconds.
- Breaks happen at sentence punctuation (`. ! ? ।`), at clause punctuation (`, ; : —`) once the cue already holds 14 characters, and at pauses of 350 ms or more between words; scene boundaries are forced breaks, and a break is forced before a cue would exceed 2 lines or the maximum duration. A single token longer than a line is split across the two lines and truncated with an ellipsis beyond that.
- A cue starts at its first word's start and ends 120 ms after its last word's end, trimmed to the next cue's start.

**Formats**

- **WebVTT** (`subtitles.vtt`) for the player's captions track, with `HH:MM:SS.mmm` timestamps.
- **SRT** (`subtitles.srt`) for platforms and downloads, with `HH:MM:SS,mmm` timestamps.
- **ASS** for optional burn-in. One file per aspect at that aspect's resolution, styled with the brand fonts (Geist, Noto Sans Devanagari for Hindi), white text on a translucent dark box, placed in the caption band below the safe area (font size 48 px at 16:9 and 36 px at 9:16 and 1:1, bottom margin 12, 220 and 50 px, so the box stays inside the 160, 420 and 200 px bands). The burn-in uses ffmpeg's `ass` filter with the runtime font directory.

Subtitles are generated from the same word timings as the animation, so they align with the audio by construction; the integration suite checks the cue times against the word timings.

## 6. Voices

The `voices` module owns `voices` and `voice_consents`; the audio engine only knows `VoiceRef`.

**Built-in voices.** An admin sync (`POST /v1/admin/voices/sync`) pulls the provider's voice list into the table as `disabled` rows (new voices only; existing rows keep their curation). Admins expose a voice by setting its name, language and tags and enabling it; exposing generates a preview clip (a fixed sentence per language, cached under `voice-preview/`). Users see only `ready` built-in voices and their own cloned voices. The default voice in `user_preferences` accepts only a voice the user can select.

**Cloning.** [ADR 0027](adr/0027-voice-consent-verification.md):

1. The user accepts the consent statement (text and version from runtime settings `voices.consent_statement` and `voices.consent_statement_version`) and the API opens an attempt in Redis for one hour with a random consent sentence.
2. The browser records the sentence, plus samples (recorded or uploaded) of 30 seconds to 5 minutes in total. Each file is validated (leading bytes of a known audio container, ffprobe with a demuxer allowlist, exactly one audio stream and no video or other stream, a full decode that must succeed, size and duration limits measured on the decoded audio) and transcoded to a mono 44.1 kHz WAV through pipes; only the transcoded file is stored, under `voice/u/<userId>/<voiceId>/`.
3. On submit the attempt becomes a `pending` voice and the `voices.clone` task runs: transcribe the consent recording, require a normalized word similarity of at least 85% with the sentence, create the voice at the provider, generate a preview, write the `voice_consents` row and mark the voice `ready`. A mismatch fails the voice with `consent_mismatch` and deletes its files.
4. The number of cloned voices per user is the runtime setting `voices.max_cloned_per_user` (default 3). Cloning can cost credits through the Phase 7 reservation flow: `voices.clone_credit_cost` (default 0) is reserved at submit, committed on `ready` and released on failure. The clone reservation has its own lifetime, the stall age plus the full task retry window plus a margin (about 11 hours), never the global `BILLING_RESERVATION_TTL_SECONDS`. The commit runs in the same transaction that marks the voice `ready`: if the reservation is no longer active the transaction rolls back, the provider voice and the files are deleted and the voice fails with `credit_reservation_expired`, so a clone never becomes `ready` without a charge.

**Consent evidence in Redis.** Two short-lived records carry the evidence before it reaches the database. The attempt (`voices.attempt`, lifetime `VOICES_ATTEMPT_TTL_SECONDS`, default one hour) holds the user ID, the random sentence, the accepted statement version and hash and the asset IDs of the uploaded files; it is deleted when the attempt is submitted and otherwise expires on its own. The submission record (`voices.submission`, fixed 24 hours) is written at submit and holds the voice ID, user ID, sentence, statement version and SHA-256, acceptance time, the client IP address and user agent, the asset IDs and the reserved credits so the retried `voices.clone` task can write the `voice_consents` row; the task deletes it when the voice becomes `ready` or fails, and Redis expires it after 24 hours at the latest. The IP address and user agent are personal data: they leave Redis only through the `voice_consents` row, which follows `retention.md`, and a Redis snapshot or append-only file taken inside those windows holds them for that long.

**Voice API.**

| Route                                                                                                                                           | Purpose                                                                                                                                                                                                                                          |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /v1/voices`, `GET /v1/voices/{voiceId}`                                                                                                    | Ready built-in voices and the caller's own cloned voices in any status (filters `language`, `kind`; cursor pagination). `failureCode` explains a failed clone                                                                                    |
| `GET /v1/voices/{voiceId}/preview`                                                                                                              | Short-lived presigned URL of the preview clip under `voice-preview/`; `404 voice_preview_not_ready` until it exists                                                                                                                              |
| `POST /v1/voices/clones`                                                                                                                        | Accept the consent statement (`statementVersion` must equal the current version, `409 consent_statement_outdated` otherwise) and open an attempt (`voices.clone`, 10/hour); the response carries the sentence, the statement text and the limits |
| `PUT /v1/voices/clones/{attemptId}/consent-recording`, `POST .../samples`, `DELETE .../samples/{sampleId}`, `GET /v1/voices/clones/{attemptId}` | Upload (`voices.upload`, 60/hour), replace, remove and inspect the attempt. Only the transcoded WAV is stored                                                                                                                                    |
| `POST /v1/voices/clones/{attemptId}/submit`                                                                                                     | Needs an `Idempotency-Key`; validates, reserves `voices.clone_credit_cost` credits when it is above zero (`402 insufficient_credits`), creates the `pending` voice and defers `voices.clone` (`202`)                                             |
| `DELETE /v1/voices/{voiceId}`                                                                                                                   | Own cloned voices only; `409 voice_busy` while pending; `502 voice_provider_unavailable` keeps the voice so the user can retry                                                                                                                   |
| `GET /v1/admin/voices`, `POST .../sync`, `PATCH .../{voiceId}`, `POST .../{voiceId}/preview`                                                    | Built-in catalog curation with `voices.manage`, audited; cloned voices are `404` here                                                                                                                                                            |

The `voices.clone` task retries only infrastructure errors (provider unavailable, timeout or rate limit, storage, database, Redis); a provider rejection or a consent mismatch fails the voice at once with `sample_invalid`, `provider_failed`, `preview_failed`, `transcription_failed`, `credit_reservation_expired` or `consent_mismatch`, deletes its files and releases the reserved credits by looking the active reservation up by reference (`voice_clone`, voice ID), which makes the release idempotent. `voices.sweep` (hourly) fails clones stuck in `pending` for two hours with `clone_stalled` through the same path, so their reservation is released too, and deletes uploads of attempts that were never submitted after three hours. The failure and the release share one transaction behind the voice row lock, so a clone is either finalized and charged or failed and released, never both. The user purge releases the reservation of a still pending clone.

**Upload limits.** Voice uploads are read as a counted stream behind authentication and the `voices.upload` rate limit: a declared `Content-Length` above the cap is refused with `413` before any byte is read, and a body that exceeds `VOICES_SAMPLE_MAX_BYTES` plus 256 KiB of multipart overhead is cut off at that point instead of being spooled to disk. The proxy adds its own `request_body` cap above the largest configured upload ([render.md](render.md) section 13).

**Deletion.** `DELETE /v1/voices/{id}` deletes the voice at the provider, its samples and preview from storage, its `tts_cache` entries and the voice row; the consent evidence stays for the period in `retention.md`. The user purge deletes every voice of a purged user the same way before the rows cascade.

## 7. Configuration

| Variable                                                             | Default                               | Meaning                                                    |
| -------------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------- |
| `AUDIO_TTS_PROVIDER`                                                 | `elevenlabs`                          | Provider for synthesis when a voice does not pin one       |
| `AUDIO_TRANSCRIBER`                                                  | `elevenlabs`                          | Provider for alignment and consent transcription           |
| `ELEVENLABS_API_KEY`                                                 | none                                  | Required in deployed environments                          |
| `ELEVENLABS_API_BASE_URL`                                            | `https://api.elevenlabs.io`           | HTTPS origin                                               |
| `ELEVENLABS_TTS_MODEL`, `ELEVENLABS_STT_MODEL`                       | `eleven_multilingual_v2`, `scribe_v1` | Models                                                     |
| `ELEVENLABS_COST_MICROS_PER_1K_CHARS`                                | `180000`                              | Price used for usage records                               |
| `OPENAI_API_KEY`                                                     | none                                  | Needed only when OpenAI is selected                        |
| `OPENAI_API_BASE_URL`                                                | `https://api.openai.com`              | HTTPS origin                                               |
| `OPENAI_TTS_MODEL`, `OPENAI_TRANSCRIBE_MODEL`                        | `gpt-4o-mini-tts`, `whisper-1`        | Models                                                     |
| `OPENAI_COST_MICROS_PER_1K_CHARS`                                    | `15000`                               | Price used for usage records                               |
| `VOICES_CONSENT_MATCH_THRESHOLD`                                     | `0.85`                                | Minimum similarity between consent sentence and transcript |
| `VOICES_SAMPLE_MIN_TOTAL_SECONDS`, `VOICES_SAMPLE_MAX_TOTAL_SECONDS` | `30`, `300`                           | Total sample duration bounds                               |
| `VOICES_SAMPLE_MAX_BYTES`                                            | `26214400`                            | Size limit per uploaded file                               |
| `VOICES_ATTEMPT_TTL_SECONDS`                                         | `3600`                                | Lifetime of a clone attempt                                |

In `PROVIDERS_MODE=fake` the fake provider, transcriber and cloner are used and no key is read. Runtime settings (editable in the admin console, validated, audited): `voices.max_cloned_per_user`, `voices.clone_credit_cost`, `voices.consent_statement`, `voices.consent_statement_version`.
