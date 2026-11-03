# Overdub: return source loudness as soon as dubbed Russian speech stops

**Status:** P1 source-bound real-video mixer fix, 2026-11-03. This follows
`docs/p1-source-speech-coverage-20261103.md`.

## Defect reproduced on the real original source

The November 3 first full 32-cue Russian research video used a `-16 dB`
original bed throughout each translated English cue, with a 300 ms transition
only at the **source subtitle window's end**, even if the synthesized Russian
voice had stopped several seconds earlier. In the first vocal example:
Russian voice has already stopped ~22s, but original singing was held at
-16 dB until the enclosing English source cue ended at **25.64s**.

This was a mixer bug, not proof that all needed vocal demonstrations were
properly labeled by A4. The user's observation was verified on source,
old mixed PCM and new mixed PCM, all on the exact 48k original clock.

## Small existing-mixer-only fix

`app.audio.overdub._voice_activity_intervals` scans the already-produced,
voice-only dubbing WAV in 20 ms windows; detects voiced PCM samples at
amplitude >=100; merges brief same-sentence gaps; ducks the original
shortly before speech onset and restores it after ~60ms trailing hold with
a 25ms cosine fade. No external VAD model, audio re-transcription,
new UI state, or new library. The original source A4 partition continues
to own all PRESERVE and REVIEW boundaries. The existing `OverdubLevels`
still controls the original/dubbed balance **while RU speech is active**.
Entirely silent TTS means original audio unchanged throughout.

The 300ms A4-boundary transition remains for cases where an active voice
reaches the boundary. This fix does not alter the source cue clock, event
classification, timings, TTS text, voices or user/source media.

## Real outcome

Both final user-facing bilingual MP4s are only in private local report folder
`~/Documents/PersoDub-Research/reports/p1-fast-original-return-20261103/`:

- `full-32-fast-return-bilingual.mp4`: all 32 transcribed source cues in RU.
- `exercises-fast-return-bilingual.mp4`: same 32 synthesized RU clips
  plus the separate **provisional** original exercise masks from the prior
  research demo. This remains research, not human A4 gold.

Each output is ~206 MB, dual audio streams Overdub + Original and EN/RU
subtitles. Both are constructed using the **exact pre-existing Russian TTS
WAV and original source PCM**. This was a pure mixer re-export.

### First singing example, measured on actual WAVs

At 22.20-22.70s, 23.00-23.50s, 24.00-24.50s and 25.00-25.50s,
the new full-RU mix is **byte-identical to the full-volume original source
PCM**. The previous mix at 23s reduced the source RMS from 2810 to 445;
the new mix has RMS 2810. At 24s source RMS 4090, old mix 648, new
mix 4090. At 25s source RMS 3792, old mix 601, new mix 3792.
The actual voice activity ends before 22.2s and the loudness returns
rather than waiting for the 25.64s subtitle boundary.

Independent technical audit:
`final-fast-return-technical-qa.json`. The final MP4s each retain exactly
**7039 original source video packets** and **10107 original AAC packets**,
bitstream SHA-identical in order; A4 protected source PCM exact:
**1,639,344 frames** full translation, **2,209,584 frames** experimental
exercise-preserved version. Each passes same early example source PCM
comparison. The source video SHA remains
`27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`.

This does not claim to repair all source ASR word errors or establish
human-reviewed singing boundaries. The first full 32-cue file is still the
complete **transcribed-cue** comparison baseline.

## Verification

Added mixer regression tests for:
- original return **inside** an otherwise translated 3s cue after the
  1.2s Russian TTS completes;
- short pauses between Russian words **do not pump** original gain;
- a completely silent TTS clip leaves original full-volume and bit-exact;
- source A4 PRESERVE sample region remains exact even with active TTS.

Older tests expecting source volume to remain ducked after TTS stops were
updated deliberately, rather than preserving the defective behavior.
