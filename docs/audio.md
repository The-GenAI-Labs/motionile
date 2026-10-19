# Audio engine

Narration, mixing, loudness, subtitles and voices. The render pipeline that consumes them is in [`render.md`](render.md). Code lives in `apps/server/src/motionile/engine/audio` (providers, alignment, assembly, mixing, subtitles) and in the `media` and `voices` modules (cache, usage, orchestration, HTTP).

Decisions: [ADR 0022](adr/0022-tts-cache-by-content-hash.md) (TTS cache), [0023](adr/0023-music-library-and-licensing.md) (music), [0027](adr/0027-voice-consent-verification.md) (voice consent).

## 1. Text-to-speech providers

`engine/audio/providers/base.py` defines the interfaces. The engine never imports a module: the cache, the usage log and the voice records are reached through ports that `modules/media` implements.

```python
class TTSProvider(Protocol):
    name: str
    returns_native_timestamps: bool

    async def synthesize(self, text: str, voice: VoiceRef, options: SynthesisOptions) -> SynthesisResult: ...
```

- `VoiceRef` is the provider and the provider voice ID. `SynthesisOptions` carries language, speed, stability and output format. `SynthesisResult` is the audio bytes with their content type, the duration in milliseconds, the word timings (`text`, `start_ms`, `end_ms` per word, relative to the audio start), the billed characters, the cost in micro-dollars and the model.
- The duration is measured from the decoded audio with ffprobe, never taken from the provider. Word timings are clamped to it and made monotonic.

| Provider     | Timestamps                                                                                                                  | Notes                                                                                                                                                                      |
| ------------ | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `elevenlabs` | Native. Uses `POST /v1/text-to-speech/{voice_id}/with-timestamps`, which returns base64 audio and a per-character alignment | Character alignment is converted to words: the text is split on whitespace, each word starts at its first character's start time and ends at its last character's end time |
| `openai`     | None. `POST /v1/audio/speech` returns audio only                                                                            | An `Aligner` derives word timings from a word-level transcription of the generated audio                                                                                   |
| `fake`       | Synthetic                                                                                                                   | Deterministic tone (or silence) whose length follows the text, with plausible per-word timings; used whenever `PROVIDERS_MODE=fake`                                        |

All outbound calls go through `SafeHttpClient`. API keys are `SecretStr` settings (`ELEVENLABS_API_KEY`, `OPENAI_API_KEY`) and never reach logs.

### 1.1 Alignment

`Aligner.align(audio, text, language)` runs a `Transcriber` (word-level transcription) and maps the source words onto the transcribed words with a sequence match. Source words with no counterpart (numbers, punctuation, abbreviations that the transcript spells differently) get timings interpolated between their matched neighbors. The result always has exactly one timing per source word.

Transcribers: ElevenLabs speech-to-text (`scribe_v1`), OpenAI `whisper-1` with word timestamp granularity, and a fake that derives words from the audio length. `AUDIO_TRANSCRIBER` selects one. The same interface transcribes the consent recording of a voice clone.

## 2. Caching and usage

Every synthesis goes through `tts_cache`:

- **Key:** SHA-256 over length-prefixed provider, model, provider voice ID, normalized text (NFC, whitespace collapsed and trimmed) and the synthesis settings.
- **Hit:** the stored audio and word timings are returned; nothing is synthesized, no usage row is written and `hit_count` and `last_used_at` are updated.
- **Miss:** the provider is called, the audio is stored as a system asset under `tts/`, the entry is inserted, and one `usage_records` row is written through `motionile.modules.credits.record_usage`: stage `tts`, the provider, the model, the characters, the cost in micro-dollars and zero credits.
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
- Breaks happen at sentence punctuation (`. ! ? ।`), at clause punctuation (`, ; : —`) and at pauses of 350 ms or more between words; a break is forced before a cue would exceed 2 lines or the maximum duration.
- A cue starts at its first word's start and ends 120 ms after its last word's end, trimmed to the next cue's start.

**Formats**

- **WebVTT** (`subtitles.vtt`) for the player's captions track, with `HH:MM:SS.mmm` timestamps.
- **SRT** (`subtitles.srt`) for platforms and downloads, with `HH:MM:SS,mmm` timestamps.
- **ASS** for optional burn-in. One file per aspect at that aspect's resolution, styled with the brand fonts (Geist, Noto Sans Devanagari for Hindi), white text on a translucent dark box, placed in the caption band below the safe area. The burn-in uses ffmpeg's `ass` filter with the runtime font directory.

Subtitles are generated from the same word timings as the animation, so they align with the audio by construction; the integration suite checks the cue times against the word timings.

## 6. Voices

The `voices` module owns `voices` and `voice_consents`; the audio engine only knows `VoiceRef`.

**Built-in voices.** An admin sync (`POST /v1/admin/voices/sync`) pulls the provider's voice list into the table as `disabled` rows (new voices only; existing rows keep their curation). Admins expose a voice by setting its name, language and tags and enabling it; exposing generates a preview clip (a fixed sentence per language, cached under `voice-preview/`). Users see only `ready` built-in voices and their own cloned voices. The default voice in `user_preferences` accepts only a voice the user can select.

**Cloning.** [ADR 0027](adr/0027-voice-consent-verification.md):

1. The user accepts the consent statement (text and version from runtime settings `voices.consent_statement` and `voices.consent_statement_version`) and the API opens an attempt in Redis for one hour with a random consent sentence.
2. The browser records the sentence, plus samples (recorded or uploaded) of 30 seconds to 5 minutes in total. Each file is validated with ffprobe (a real audio container, an audio stream, no video stream, size and duration limits) and transcoded to mono WAV; only the transcoded file is stored, under `voice/u/<userId>/<voiceId>/`.
3. On submit the attempt becomes a `pending` voice and the `voices.clone` task runs: transcribe the consent recording, require a normalized word similarity of at least 85% with the sentence, create the voice at the provider, generate a preview, write the `voice_consents` row and mark the voice `ready`. A mismatch fails the voice with `consent_mismatch` and deletes its files.
4. The number of cloned voices per user is the runtime setting `voices.max_cloned_per_user` (default 3). Cloning can cost credits through the Phase 7 reservation flow: `voices.clone_credit_cost` (default 0) is reserved at submit, committed on `ready` and released on failure.

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
