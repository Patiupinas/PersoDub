# PersoDub P1 - Full transcribed speech coverage, source-exact Russian Overdub

**Date:** 2026-11-03. **Branch:** `feature/p1-full-speech-coverage-20261103` on the tested native-Russian/diarization branch. Experimental source-language and vocal-exercise decisions are **not human A4 ground truth**. User video, model weights, audio, translations and QA logs remain private on Mac and are not published with this code.

## User-visible defect and fix

The previous `research-fixed-russian-17-cues/dubbed.mp4` was an A4 research preview, not a complete lesson: only **17/32** Russian transcribed speech cues were synthesized; the other 15 speech cues were passed through as original English. A technically successful mux and unchanged protected source PCM did not prove that *all normal spoken lines were translated*. The user noticed this while listening.

The real four-minute lesson has a source video SHA-256 of `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`. The exact original, video-cut PCM is **11,262,384 frames** at 48 kHz stereo, SHA-256 `e5687f71c121ea75fb1aa8d2da700e856cfd3b03ca7149e74e7c6e20702e4dfe`. Do not substitute the differently clocked 234.684s independent source WAV.

### Permanent product change: report speech coverage, not just export success

The existing A4 voice selection in `app.audio.overdub.select_translatable_cues` already returns exact source provenance `source_cue_number`. A new small, pure `source_speech_coverage(source_cues, selected, source_frames)` computes:

- **Original 48k PCM-clock-bound source cues and selected TTS cues**, with exact original numbered cue mapping and duplicate/stale selection rejection.
- **Translated source speech cues / total transcribed speech cues** and the exact numbers left in original English.
- **Union of source speech seconds**, **union of selected translated speech seconds** and **outside-transcript seconds**, counting overlapping cues only once, rather than equating all gap audio with missing English narration.
- Explicit statuses `ALL_TRANSCRIBED_SPEECH_CUES_SELECTED`, `INCOMPLETE_SOURCE_SPEECH_COVERAGE`, or `NO_TRANSCRIBED_SPEECH`.

`app.pipeline.run_dub` computes this at the **real A4 selection boundary before TTS**, writes `speech_coverage.json`, logs coverage and returns it under `result.a4_synthesis.coverage`. The Script pane header shows `Speech translated: X/Y` with a clarification that **100% selected transcribed speech is not human A4 certification for exercises**. Old jobs lacking a coverage receipt show nothing, never an invented 100% status. Tests cover real pipeline persistence and UI partial/complete/unknown cases.

**This is a coverage diagnostic, not a new A4 approval authority.** A true protected singing exercise *inside* an ASR speech cue may still be classified as speech; that requires source listening and finer boundaries, rather than automatically translating or silencing a demonstration.

## Actual private real-audio trial: all 32 source speech cues

All evidence and actual media: `~/Documents/PersoDub-Research/reports/p1-full-speech-coverage-20261103/`.

Selected source: 32 original-language cue windows across **200.480s** of the **234.633s** video, covering **85.4441% of the original video clock**; **34.153s** of noncue gaps remain untouched original sound. All **32/32 speech-cue Russian WAVs** were generated on the real `Silero v5.6 RU` TTS backend and assembled through real source-bound PersoDub Overdub/Mux. Transcribed-cue coverage is 100%; this is explicitly **not** 100% verified individual source-language words, translation semantics, or vocal-demo boundaries.

The source-cache transcript initially carried a lone CAM++ `SPK1` label for a **1.08s** line at 145.64s, among forty `SPK0` lines. Independent CAM++ inference on the real original 32-cue source run found all 32 were `SPK0`. The private corrected trial kept the old source speaker labels but mapped both to **one outgoing native-Russian `VOICE_01` (`aidar`)**, so the narrator does not change voice mid-lesson. This is provisional source-diarization evidence, not a human identity label.

An independent bounded 74-cue English source ASR exposed source speech missing or inaccurately transcribed around **2:30-2:56**. The private research source/translated SRT corrected seven Russian speech cues and several clock edges. Four additional Russian cue wordings with spelled-out letters/notes were simplified for intelligible native pronunciation and more natural pacing. These translations are research candidates, not bilingual human semantic gold.

Two original trial voice clips originally cut **1.098s** and **1.258s** from their source-clock slots. Shorter corrected Russian sentences removed these meaningful truncations. The final trial has only three sub-audible timing trims totalling **0.021s**, with leakage/echo QA PASS after one cancel-echo rerender. The native-Russian voice assignment is `VOICE_01 -> aidar`; no source timbre clone was requested or used.

### Independent exact final result

Private sources: `full-speech-natural-result.json`, `full-speech-natural-technical-audit.json`, `full-speech-natural-32-independent-asr.json`, `final-user-facing-files-qa.json`.

- **7 word errors / 358 Russian reference words = 1.9553% WER**, independently checked with cached Faster-Whisper Large-v3 CPU int8. All 32 generated WAVs covered; 28 have individual SHA equality with a previously measured run and 4 changed WAVs received new independent ASR. Six errors are in the final Patreon / URL outro; one in a soft-singing cue. This is **lexical recoverability**, not human accent MOS or proof of translated meaning.
- Both final MP4s have **two selectable audio tracks** (default `Overdub`, optional `Original`) and two embedded subtitle tracks (English source and Russian translation).
- The original **7,039 video packets** and **10,107 original AAC packets** are **byte-sequence SHA-identical** to the input in both final user-facing MP4s, verified from the final files themselves. Original PCM is sample-for-sample identical in every protected non-TTS segment.
- **Primary full-speech video**: `research-russian-full-32-natural-demos/dubbed-all-32-ru-en-subtitles.mp4`. Original PCM protected for **34.153s**, Russian spoken cue windows for **200.480s**.
- **Optional preliminary exercise-preserving video**: `research-russian-full-32-natural-demos/dubbed-exercise-protected-ru-en-subtitles.mp4`. Same 32 generated Russian WAVs, but another **11.88s** of original audio is restored over estimated demonstration intervals (17.76-25.64s, 59.5-61.5s, 65-67s). Original PCM protected for **46.033s**, translated timeline windows **188.60s**. These three short masks are a research hypothesis informed by uncalibrated AST cues, **not verified A4 labels**. A spoken word occurring inside such a mask may be original English; the primary video is the most complete Russian voiced transcript.
- Both files are real ~206MB MP4s, all media/private outputs stay on the Mac. Model weights, private scripts/audio and original video are not committed.

### Cross-check scope and unresolved source truth

A separate bounded Whisper ASR returned 74 English source cues. Five of these had less than 50% temporal overlap with the 32-cue SRT: around **80-89s, 124-130s, 140-147s, 197-199s, and 205-212s**. Several are sung alphabets/breath demonstrations, punctuation noise, or ASR boundary disagreements; without source listening they **cannot all be certified as vocal exercises**. This evidence remains available for review. Thus do not label the experiment a fully human-approved singing-preserving production release.

The next highest-value action is listen to the two actual video variants with the 74-cue original ASR during gaps, correct semantic errors and certify A4 singing vs speech windows. The repeatable product coverage receipt will identify future incomplete 17/32 jobs even if FFmpeg finishes successfully.

## Verification contract

New unit tests for complete, partial, missing, overlapping, stale/duplicate source cue, empty and beyond-source coverage; fake real pipeline validates coverage JSON and return field; UI tests validate complete, partial and missing/old-job header display. Run the full repository Python, Web UI and Desktop suites on the final commit before treating this work as published.
