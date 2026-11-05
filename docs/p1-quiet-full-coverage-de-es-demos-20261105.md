# P1-O: Quieter Overdub and real DE/ES Russian examples

Date: **2026-11-05**. Base: P1-N draft PR #57. P1-O is **research/demo and quieter default** only, not human-approved full A4 gold and not a product release.

## Why this update is needed

The owner reported the Russian dub was **still too loud** after the -8 dB P1-N change and **part of the translation was missing**. The immediate visible example in P1-N was only a **two-source-cue research comparison** of a 234.684-second lesson: it contained translated TTS at 0.35-8.9 and 49.12-55.50 seconds, with every other original interval left unchanged. It was a model shootout, not a full lesson translation.

An older 32/32 Silero male-voice asset existed, so use it rather than restarting costly synthesis. Its `speech_coverage.json` proves all **32 source-transcript cues were synthesized**, but does **not** prove every independent source word was recognized or that all A4 review spans were approved.

The prior provisional singing protection mask suppressed the **entire** transcript cue 3, 17.76-25.64 s, mixing spoken commentary with a vocal demonstration. Two other cues had partial singing masks. An independent source Whisper/ASR also found candidate words in eight gaps between the current 32 source subtitle cues, but several of these are one-word repetitions, singing snippets, or alternative ASR boundaries, **not** verified missing translatable sentences. These are documented in the private `missing-source-asr-audit.json` for review, not blindly auto-approved.

## New English lesson research output

Root on private Mac (not uploaded to Git): `~/Documents/PersoDub-Research/reports/p1-voxcpm2-overdub-20261105/full-lesson-volume-coverage-20261105/`.

- `full32-male-silero-minus16.mp4` and `full32-male-silero-minus20.mp4`, each a real **234.684-second** bilingual MP4.
- Both retain the exact same source video, original AAC packets and original/source dual-audio choice, plus original-language and Russian subtitle streams.
- The existing **32 native Russian Silero `aidar`** synthesized source-cue WAVs are reused unchanged.
- The revised **research-only** A4 mask translates the spoken portion of source cue 3 at 17.76-22.05 s and protects its later 22.05-25.64 s vocal demonstration, instead of retaining the entire 17.76-25.64 s cue. Two other transcript cues remain partially masked around vocal syllables. This is NOT independent, human-verified singing classification.
- `audible-source-cue-coverage.json` checks the **actual Russian voice activity intersected with the translated A4 intervals**, not only existence of 32 subtitle lines. **32/32** source cues have nonzero audible Russian samples, and **none are fully muted**. That metric does not prove every word is voiced correctly or that the other partial song/speech boundaries are exact.
- `full32-male-silero-minus16-audit.json` and `full32-male-silero-minus20-audit.json`: **7,039/7,039** original video packet SHA256s and **10,107/10,107** original AAC packet SHA256s exactly unchanged in BOTH final videos.
- The difference is only the translated gain: source under dub `-16 dB`, Russian voice `-16 dB` or **`-20 dB`**, 300 ms transition for this reproducible cached mix. No TTS re-generation or video re-encoding was used.
- Private LAN review page during tests: `http://192.168.0.30:18772/full-lesson-volume-coverage-20261105/index.html`, includes 72-second previews and full 3m54s videos.

## Product behavior

For **new** Overdub jobs, change the default Russian translated voice level from `-8 dB` to **`-16 dB`**, with source-under-dub remaining `-16 dB`. Keep `-20 dB` as an adjustable, separately demonstrated quieter option. The canonical defaults now match in mixer, selective export CLI, API request models and the UI form. Update numeric PCM mixer regression expectations. A previously saved job that explicitly chose -8 or -2 remains unchanged; only default values for new requests are affected. The fixed Russian source-register routing from P1-N is unchanged.

Do not imply the project itself has an automatically generated full-lesson VoxCPM2 take: full32 used existing **Silero** male voice. VoxCPM2 is still an opt-in alternative requiring a separate model/service and a complete source-bound pass.

## Real German/Spanish YouTube -> Russian research demos

The project had earlier actually downloaded legitimate short source clips and obtained candidate translations (P1-K report, `docs/p1-de-es-translation-live-20261104.md`). This update produced **real Russian speech audio**, source-aligned and untruncated, with two-level Overdub and captioned videos.

Private Mac: `~/Documents/PersoDub-Research/reports/p1-de-es-translation-20261104/audio-dub-20261105/`.

| Clip | Original YouTube | Source voice register | Russian fixed TTS | ASR/translated candidate cues | Real duration |
| --- | --- | --- | --- | ---: | ---: |
| German, Dirk Hoppe's singing-breath exercise | `https://www.youtube.com/watch?v=qXFb5h4cYWc` | male-sounding pitch `F0 p25` 114-139 Hz in three tested snippets | Silero `aidar` | **22/22** | **80.0 s** |
| Spanish, unComo vocal-breathing tutorial | `https://www.youtube.com/watch?v=_CjGC5lwQuU` | female-sounding pitch `F0 p25` 209-226 Hz in three tested snippets | Silero `kseniya` | **12/12** | **80.0 s** |

Actual generated `de/de-ru-overdub-minus16.mp4`, `de/de-ru-overdub-minus20.mp4`, `es/es-ru-overdub-minus16.mp4`, `es/es-ru-overdub-minus20.mp4`. Each is **80 seconds** with a caption/reference slide track (original ASR and Russian words), **two selectable audio tracks**, preserved original audio under dub, and actual voices generated using the existing pinned Silero RU v5.6 model. The original YouTube videos are separately linked, not misrepresented as embedded dubbed copies of the visual YouTube source.

The initial literal translations contained 10 German and 4 Spanish utterances that could not fit their original source-clock slots naturally. Local research-only Russian text edits shortened those 14 lines while retaining the source-relevant concepts; auditable original and shortened candidate strings live in the **private** `fitted-tts-timing.json` manifests. All 34 generated WAVs were retained; only small leftover timing variance used `ffmpeg atempo`, maximum `1.219` for one German cue and `1.064` for one Spanish cue. Final WAVs were checked for full placement before the next source cue; **22/22 German and 12/12 Spanish clips** have zero TTS sample truncation. Original/source ASR and translation remain unapproved candidates, not semantic gold. The demos are the **first 80 seconds** of longer YouTube sources, not full-lesson translations.

Private LAN review page (HTTP 200 verified, all 4 MP4s checked as 80.0 seconds with a video stream and 2 audio streams): `http://192.168.0.30:18773/audio-dub-20261105/index.html`. No video/audio, model checkpoints, source transcript files or user identifiers are committed.

## Evidence and next gate

- Mac real-video packet identity checked for both full32 English videos, source-locked at original 48 kHz.
- DE/ES source-linguistic timbre routing based on actual measured F0; no group-order guessing.
- DE/ES SHA256-bounded per-line synthesis and full-voice placement QA in `de/technical-qa.json` and `es/technical-qa.json`.
- The source-text coverage assertion is **relative to the current transcript**, not proof of full real-world source word recall. A4 singing-boundary adjudication and independent bilingual semantic review are still open.
- Adjust the **new-job default** to -16 dB, not -20 dB without a listening decision. Both mixes are provided so the owner can choose; past explicit settings retain their authority.

Next: use owner feedback on comparative English, German and Spanish audio at -16 vs -20 to choose the target product mix; then revisit contested source ASR sections and A4 song/lecture boundaries against real audio, not by extrapolating transcript counts.

No main merge, no GitHub Actions, no private lesson media uploaded.
