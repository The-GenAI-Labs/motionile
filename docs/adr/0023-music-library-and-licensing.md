# 23. Music library and licensing

- Status: Accepted
- Date: 2026-10-19

## Context

Videos may carry a background music bed. Music that is not licensed for commercial redistribution exposes Motionile and its users to takedowns, and attribution requirements are easy to forget.

## Decision

- Music comes only from `music_tracks`, uploaded by admins with `music.manage`. There is no user upload and no external music source.
- A track cannot exist without a license name and an HTTPS license URL (a database check), and may carry the attribution text the license requires. Audio is validated with ffprobe at upload, transcoded to a standard format and stored under `music/`.
- A new track is inactive. Only active tracks can be selected, and `create_render` rejects an inactive or unknown track with `music_track_unavailable`.
- A render that uses a track records the track ID in its options, so the license and attribution that applied stay known after the track is deactivated.
- Attribution text is returned with the rendition, so the player and publishing connectors can show it.
- The runbook `voices-and-music.md` states who may add tracks, which licenses are acceptable and how to take one down.

## Consequences

- Every track in a published video has a recorded license and a contact trail.
- Taking a track down means deactivating it; videos already rendered keep their mixed audio, and the runbook covers re-rendering when a license is withdrawn.
- Admins carry the duty of checking licenses; the system enforces that one is recorded, not that it is valid.
