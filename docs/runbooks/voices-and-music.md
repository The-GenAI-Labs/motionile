# Voices and music

How to run the built-in voice catalog, the licensed music library and voice misuse reports. Voices and music are the two inputs of a video that Motionile does not generate itself, so each one needs a recorded right to be used: a provider voice that may narrate commercial videos, a licence for every music track, and a verified consent for every cloned voice. Design background: [audio.md](../audio.md), [ADR 0023](../adr/0023-music-library-and-licensing.md) and [ADR 0027](../adr/0027-voice-consent-verification.md). Retention rules: [retention.md](../db/retention.md).

Placeholders:

| Placeholder           | Meaning                                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `<ENV>`               | `staging` or `production`                                                                                                                              |
| `<API_DOMAIN>`        | `api.<DOMAIN>` or `api.<STAGING_DOMAIN>`                                                                                                               |
| `<BUCKET>`            | Media bucket name: `grep -E '^STORAGE_BUCKET=' /srv/motionile/.env` on the instance, or `tofu output -raw media_bucket_name` in `infra/aws/envs/<ENV>` |
| `<VOICE_ID>`          | `voices.id`, a UUID                                                                                                                                    |
| `<PROVIDER_VOICE_ID>` | `voices.provider_voice_id`, the voice's ID at the provider                                                                                             |
| `<USER_ID>`           | `users.id` of the voice owner                                                                                                                          |
| `<TRACK_ID>`          | `music_tracks.id`, a UUID                                                                                                                              |

SQL runs in the Neon Console **SQL Editor** for branch `<ENV>`, database `motionile`, role `motionile` ([neon-setup.md](neon-setup.md#4-pre-create-the-extensions) shows the editor). Shell commands marked "on the instance" run as `deploy` in a Session Manager shell ([access-and-operations.md](access-and-operations.md#1-open-a-shell-on-the-instance)).

## 1. Who may do what

| Task                                                    | Permission                   | Where                            |
| ------------------------------------------------------- | ---------------------------- | -------------------------------- |
| Sync, name, tag, expose and disable built-in voices     | `voices.manage`              | Admin console, Voices            |
| Upload, edit, activate and deactivate music tracks      | `music.manage`               | Admin console, Music             |
| Verify a voice or a track with a render                 | `render.testbed`             | Admin console, Render test bed   |
| Look up consent evidence, run SQL, delete provider data | database and instance access | Neon SQL Editor, Session Manager |

Grant the permissions through roles with `motionile.scripts.grant_role` ([bootstrap-admin.md](bootstrap-admin.md)); never edit `user_roles` by hand. There is no user upload of music and no admin can clone a voice for a user. Give `music.manage` only to people who have read section 3.

## 2. The built-in voice catalog

Built-in voices come from the speech provider. Users see only built-in voices with status `ready` and their own cloned voices.

### 2.1 Sync

1. In the admin console open **Voices** and choose **Sync from provider** (this calls `POST /v1/admin/voices/sync`).
2. Expected result: new provider voices appear with status `disabled`. Voices that already exist keep their name, language, tags and status; sync never exposes or changes anything by itself.

Sync after the provider announces new voices, and after changing `AUDIO_TTS_PROVIDER`.

### 2.2 Check, tag and expose a voice

1. Read the provider's terms for that voice. Only expose voices whose terms allow commercial narration of videos that users publish on social platforms. Voices shared by other people in a provider's community library can carry extra conditions or be withdrawn by their owner; do not expose them. Write the decision and the date in the change ticket.
2. Open the voice, play the provider sample, and set:
   - the display name (at most 80 characters);
   - the language as a BCP 47 code such as `en`, `en-IN` or `hi`;
   - tags for the picker filters: accent, gender and style.
3. Choose **Enable**. Expected result: status `ready` and a preview clip generated from the fixed sentence of that language and stored under `voice-preview/`. Play it in the console.
4. Verify end to end: open **Render test bed**, render the golden composition `kinetic-typography` with this voice and play the result. The first synthesis of new text is billed by the provider; repeat renders of the same text come from the cache.

Check what users can pick:

```sql
SELECT id, name, language, labels, provider, provider_voice_id
FROM voices
WHERE kind = 'builtin' AND status = 'ready'
ORDER BY language, name;
```

### 2.3 Disable a voice

Choose **Disable** on the voice. Expected result: status `disabled`; the voice disappears from the picker, new renders cannot select it, and renders that already exist keep their audio. Cached narration is kept until the 90-day prune removes it.

Disable a voice when the provider withdraws it, when its terms change, or when users report that it sounds wrong.

## 3. Licensed music

Music comes only from `music_tracks`. A track cannot exist without a licence name and an HTTPS licence URL (a database check), and only active tracks can be used. The system enforces that a licence is recorded, not that it is valid: the person who adds a track is accountable for that.

### 3.1 Acceptable licences

| Licence                                                                       | Accept | Condition                                                                                                                                                 |
| ----------------------------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CC0 and public-domain dedications                                             | yes    | Keep the page that shows the dedication                                                                                                                   |
| CC BY 4.0 and CC BY 3.0                                                       | yes    | Put the exact credit line the licence asks for in the attribution text                                                                                    |
| Pixabay Content License, or a similar royalty-free licence of a stock library | yes    | The licence must allow commercial use in videos and publication on social platforms; keep the licence text as it read on the day you downloaded the track |
| Paid licence bought for Motionile                                             | yes    | Written terms that allow commercial use in videos made by Motionile users, on every platform, with no end date for videos already rendered                |
| CC BY-SA, CC BY-NC, CC BY-ND and every other NC, ND or share-alike licence    | no     | They restrict commercial use, adaptation (looping, ducking and fading are adaptations) or the licence of the finished video                               |
| Tracks "for YouTube only", Content ID registered tracks, and rips of any kind | no     | Platform claims and takedowns hit users' videos                                                                                                           |
| Anything without a licence you can point to                                   | no     |                                                                                                                                                           |

### 3.2 What the licence record contains

In the database (all three are shown to admins and the attribution is shown to users):

- `license_name`: the exact name and version, at most 120 characters, for example `CC BY 4.0` or `Pixabay Content License`.
- `license_url`: an `https://` link to the licence text, or to the purchase record, at most 2000 characters.
- `attribution_text`: the credit line the licence requires, at most 500 characters, or empty when none is required. It is returned with every rendition that uses the track so the player and publishing connectors can show it.

In the evidence folder of your operations records (not in this repository and not in the media bucket), one folder per track named by its `<TRACK_ID>`:

- the licence text or purchase receipt as it read on the day of download (PDF or archived page);
- the source page of the track, the licensor's name and the date downloaded;
- the scope: commercial use, platforms, territories and term;
- the name of the person who approved the track.

### 3.3 Add a track

1. In the admin console open **Music** and upload the audio file with its title, mood, tempo and the three licence fields. Expected result: the audio is checked with ffprobe (a real audio file with one audio stream and a sane duration), transcoded to AAC in an `.m4a` at 48 kHz stereo and stored under `music/`. The track is created inactive.
2. Play it back in the console. Check that the loudness is reasonable and that the track has no spoken vocals that clash with narration.
3. Choose **Activate**.
4. Verify: render the golden composition `flow-diagram` in the **Render test bed** with this track. Expected result: the mix has the music ducked under the voice, and the rendition response carries the attribution text.

Check the library:

```sql
SELECT id, title, mood, license_name, license_url, attribution_text, is_active, created_at
FROM music_tracks
ORDER BY created_at DESC;
```

### 3.4 Take a track down

Do this as soon as a licence is withdrawn, disputed or found to be wrong.

1. Choose **Deactivate** on the track. Expected result: `is_active` is false, the picker no longer offers it, and a render that names it is rejected with `music_track_unavailable`. Do not delete the row: its licence record must stay while any render used the track ([retention.md](../db/retention.md)).
2. List the renders that carry the track:

   ```sql
   SELECT r.id, r.owner_user_id, r.source, r.status, r.completed_at
   FROM renders r
   WHERE r.options ->> 'musicTrackId' = '<TRACK_ID>'
      OR r.options ->> 'music_track_id' = '<TRACK_ID>'
   ORDER BY r.completed_at DESC NULLS LAST;
   ```

3. Decide the scope with the licensor or the person who approved the track and write it in the change ticket: usually either "no new use" (stop at step 1) or "no further distribution" (steps 4 to 6).
4. Re-render the affected videos without the track. Videos already rendered keep their mixed audio, so deactivating the track does not change them. Test bed renders are deleted 14 days after completion by the retention task; re-render the ones you still need in the **Render test bed** with no music track. Owners of other renders re-render from their library: the same options are now rejected with `music_track_unavailable`, so they pick another track or none. Email each owner the track title, the reason and the date by which the old video must stop being used.
5. Remove the old files from delivery when the scope is "no further distribution". For each affected render, on the instance:

   ```bash
   aws s3 rm "s3://<BUCKET>/media/u/<USER_ID>/renders/<RENDER_ID>/" --recursive
   ```

   Overwritten and deleted versions stay in the bucket for 30 days. To remove them at once, run this with your administrator identity (the instance role cannot delete versions):

   ```bash
   aws s3api list-object-versions --bucket <BUCKET> --prefix 'media/u/<USER_ID>/renders/<RENDER_ID>/' --output json \
     | jq '{Objects: ([.Versions[]?, .DeleteMarkers[]?] | map({Key, VersionId})), Quiet: true}' > delete-versions.json
   aws s3api delete-objects --bucket <BUCKET> --delete file://delete-versions.json
   rm delete-versions.json
   ```

6. Tell the owners of videos that were published through connected accounts to remove them there: Motionile cannot delete a post on a platform from this procedure. Send the track title, the reason and the date, and record who was told.
7. If the licensor requires the audio file itself to be destroyed, delete the object named by the track's asset and keep the row:

   ```sql
   SELECT a.storage_key FROM music_tracks t JOIN assets a ON a.id = t.audio_asset_id WHERE t.id = '<TRACK_ID>';
   ```

   ```bash
   aws s3 rm "s3://<BUCKET>/<STORAGE_KEY>"
   ```

   Then repeat the version purge above for that key.

## 4. Voice misuse reports

A report says that a voice sounds like a real person who did not agree to it, or that a cloned voice is used to deceive. Treat every report as urgent until you have judged it. The targets of this runbook are: acknowledge within one business day, contain (section 4.3) within four hours of a credible report.

### 4.1 Receive the report

Record in the ticket: when and how it arrived, who reported, whose voice they say it is, how the reporter knows (a link to a video, a render ID, a voice name, a user name) and what they ask for. Do not forward the report text to the account holder. Reply to the reporter that you are investigating and nothing more.

### 4.2 Find the voice and the consent evidence

Find the voice from what the reporter gave you:

```sql
SELECT v.id, v.owner_user_id, v.name, v.kind, v.status, v.provider, v.provider_voice_id, v.created_at
FROM voices v
WHERE v.id = '<VOICE_ID>'
   OR v.provider_voice_id = '<PROVIDER_VOICE_ID>'
   OR v.owner_user_id = '<USER_ID>';
```

Read the consent evidence. It outlives the voice, so it is found by `voice_reference` even after the voice was deleted:

```sql
SELECT c.id, c.voice_id, c.voice_reference, c.user_id, c.statement_version, encode(c.statement_sha256, 'hex') AS statement_sha256,
       c.accepted_at, c.ip, c.user_agent, c.challenge_sentence, c.transcript, c.match_percent,
       c.sample_count, c.sample_total_ms, a.storage_key AS consent_recording_key, encode(a.sha256, 'hex') AS consent_recording_sha256
FROM voice_consents c
JOIN assets a ON a.id = c.consent_asset_id
WHERE c.voice_reference = '<VOICE_ID>';
```

Listen to the consent recording with a link that lives five minutes, created with your administrator identity:

```bash
aws s3 presign "s3://<BUCKET>/<CONSENT_RECORDING_KEY>" --expires-in 300
```

The consent is sound when the recording is one voice reading `challenge_sentence`, `match_percent` is at least 85 and `statement_version` is a version the product showed. A sound consent proves that the account holder read a fresh sentence at that time; it does not prove that the samples were their own voice. Listen to the preview as well and compare it with what the reporter says. When the reporter is the person being imitated and says they never agreed, treat the report as misuse whatever the evidence shows, and contain first.

Find where the voice was used:

```sql
SELECT r.id, r.owner_user_id, r.source, r.status, r.completed_at
FROM renders r
WHERE r.options #>> '{narration,voiceId}' = '<VOICE_ID>'
   OR r.options #>> '{narration,voice_id}' = '<VOICE_ID>'
ORDER BY r.completed_at DESC NULLS LAST;
```

### 4.3 Contain

Disable the voice first. Nothing else is needed to stop new narration, because only `ready` voices can be selected:

```sql
BEGIN;
UPDATE voices SET status = 'disabled', updated_at = now() WHERE id = '<VOICE_ID>' AND kind = 'cloned' RETURNING id, status;
COMMIT;
```

Expected result: one row with status `disabled`. If the report concerns a built-in voice, use **Disable** in the admin console instead ([section 2.3](#23-disable-a-voice)) and stop here.

Decide separately whether to suspend the account; that is a user administration action in the admin console and is audited.

### 4.4 Delete the voice at the provider

On the instance. The key is read from the rendered environment file and passed to `curl` through its standard input, so it never appears in a process list or in the terminal:

```bash
key=$(grep -E '^ELEVENLABS_API_KEY=' /srv/motionile/.env | tail -n 1 | cut -d= -f2- | tr -d "'")
printf 'header = "xi-api-key: %s"\n' "$key" | curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  --request DELETE --config - "https://api.elevenlabs.io/v1/voices/<PROVIDER_VOICE_ID>"
unset key
```

Expected result: `200`. A `404` means the voice is already gone. Cloned voices exist only at the provider named in `voices.provider`; if that is another provider, use its voice deletion call with the same pattern.

### 4.5 Delete the audio in storage and the database rows

Keep the consent recording: it is the evidence. Everything else the voice created goes. First list the objects:

```sql
SELECT a.id, a.storage_key, 'sample' AS what
FROM assets a
WHERE a.storage_key LIKE 'voice/u/<USER_ID>/<VOICE_ID>/%'
  AND a.id NOT IN (SELECT consent_asset_id FROM voice_consents WHERE voice_reference = '<VOICE_ID>')
UNION ALL
SELECT a.id, a.storage_key, 'preview' FROM voices v JOIN assets a ON a.id = v.preview_asset_id WHERE v.id = '<VOICE_ID>'
UNION ALL
SELECT a.id, a.storage_key, 'narration cache'
FROM tts_cache t
JOIN assets a ON a.id = t.audio_asset_id
WHERE t.provider_voice_id = '<PROVIDER_VOICE_ID>';
```

On the instance, delete each `storage_key` returned:

```bash
aws s3 rm "s3://<BUCKET>/<STORAGE_KEY>"
```

Then remove the rows. A cache entry goes before its asset because of the foreign key, and deleting the voice sets `voice_consents.voice_id` to null and keeps the evidence row:

```sql
BEGIN;
DELETE FROM tts_cache WHERE provider_voice_id = '<PROVIDER_VOICE_ID>' RETURNING id;
DELETE FROM voices WHERE id = '<VOICE_ID>' RETURNING id;
COMMIT;
```

Expected result: the cache entries, then one `voices` row. Then delete the asset rows whose objects you removed, using the asset IDs from the listing above:

```sql
BEGIN;
DELETE FROM assets
WHERE id IN ('<ASSET_ID>', '<ASSET_ID>')
  AND id NOT IN (SELECT consent_asset_id FROM voice_consents)
RETURNING id, storage_key;
COMMIT;
```

The `NOT IN` guard makes it impossible to delete a consent recording by mistake. Check the evidence is intact:

```sql
SELECT id, voice_id, voice_reference, accepted_at FROM voice_consents WHERE voice_reference = '<VOICE_ID>';
```

Expected result: one row with `voice_id` null.

Versioned storage keeps deleted objects as noncurrent versions. Under `voice/` a lifecycle rule removes them one day after deletion. Narration and preview objects under `tts/` and `voice-preview/` follow the 30-day noncurrent retention; purge them at once with the version commands in [section 3.4](#34-take-a-track-down) using the keys you deleted.

### 4.6 Remove videos that carry the voice

Videos made with the voice contain a copy of it in their audio. When the voice is judged unauthorised, or when the person it imitates asks, remove the renders listed in section 4.2 from delivery with the commands in [section 3.4, step 5](#34-take-a-track-down). Tell the owners of videos that were published through connected accounts to remove them on the platform.

### 4.7 What stays and for how long

| Item                                                              | Kept                                                                                                                                          |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Provider copy of the voice, samples, preview, narration cache     | Deleted now (storage versions within 1 day under `voice/`, 30 days elsewhere unless purged)                                                   |
| `voice_consents` row and the consent recording                    | As long as the voice exists, plus 3 years after it is deleted, then both are deleted                                                          |
| `audit_log` entries about the account and your actions            | 2 years online                                                                                                                                |
| `usage_records` of the narration                                  | 2 years online, then rolled up without the voice                                                                                              |
| The voice ID inside `renders.options`                             | As long as the render exists                                                                                                                  |
| Database history at Neon                                          | Deleted rows remain in the restore window of the branch ([neon-setup.md](neon-setup.md#3-set-the-history-window-and-compute)) until it passes |
| Your ticket, the reporter's message and this procedure's evidence | As long as your legal advisor says; keep them out of the repository                                                                           |

Do not shorten the 3-year evidence period without the owner's written decision. Do not extend it either: it is stated in the privacy notice.

### 4.8 Notify

| Who                                | When                      | What                                                                                                                        |
| ---------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| The reporter                       | At receipt and at closing | That you received it, and afterwards that the voice was removed. Nothing about the account holder                           |
| The account holder                 | After containment         | That the voice was removed and why, in neutral wording, with a way to reply. Use the contact on the account                 |
| The speech provider                | After containment         | Report the misuse through the provider's abuse or trust and safety channel with the provider voice ID and the date          |
| The owner of Motionile and counsel | Before any disclosure     | Every report that alleges impersonation of a real person, fraud or harm; they decide on reports to authorities              |
| Authorities or other third parties | Only on legal advice      | Export the evidence rows and the consent recording (its SHA-256 is in `assets.sha256`); do not send evidence without review |

### 4.9 Close the report

Write in the ticket: the voice ID, the evidence you reviewed (consent ID, match percent, statement version), the decision, the times of containment and of each deletion, the renders removed, who was notified and when, and the date the consent evidence is due for deletion (3 years after the voice was deleted). Add an entry to the operations log.
