# A3-1 follow-up: word-to-speaker attribution (source-code adaptation)

This PR is deliberately **stacked on [A3-1 phrase groups PR #14](https://github.com/Patiupinas/PersoDub/pull/14)** and reuses its `SpeakerTurn` data type. It adds one isolated function in `app/vocal_word_speakers.py` without touching `app/pipeline.py`, inference workers, runtime dependencies or existing output files.

## Source and differences

The upstream reference is WhisperNotes [`SpeakerDiarizationAligner.swift`](https://github.com/Patiupinas/whispernotes/blob/2f863db64f41680365a0f9f8772f9147034ea675/Sources/CallRecorderCore/SpeakerDiarizationAligner.swift) at source main `2f863db64f41680365a0f9f8772f9147034ea675`, blob `143d66c678f2773469be92422cfc0346c6ad3ed2`. Tests were inspected in `Tests/CallRecorderCoreTests/SpeakerIdentityTests.swift`, including maximum overlap and nested interjection cases.

**Intentional behavior change:** the original Swift UI transcript aligner may (1) prefer a shorter turn in a perfect overlap tie and (2) interpolate text proportionally from a long cue when word timing is absent. Both are useful for readable UI transcripts but cannot prove the correct *TTS speaker or source vocal text*. Our version only attributes **pre-existing timed words** using observed overlap; competing speaker IDs, missing timings, estimated timings and ambiguous boundaries are not silently accepted.

## API

`align_word_speakers(words, turns, *, total_samples, min_overlap_samples=1)`

Inputs:

- `TimedWord(word_id, start_sample, end_sample, text, is_estimated=False)`, each with a unique word ID and immutable source-PCM half-open frame span.
- `SpeakerTurn(start_sample, end_sample, speaker_id, source)` from PR #14.
- `total_samples` from the upstream immutable decoded source PCM.

Output: sorted `AttributedWord(word, speaker_id, review_reasons)`. No new or repeated words, no conversion from floating timestamps and no invented speaker identity. Every input word produces exactly one output word. When the speaker is ambiguous, `speaker_id=None`; otherwise its original ID may be retained even if the word still needs review. `needs_review` is derived from the presence of reasons.

Review reasons are explicit: `no_speaker_evidence`, `conflicting_speakers`, `unknown_speaker`, `insufficient_speaker_coverage`, `partial_speaker_coverage`, `estimated_word_timing`, `overlapping_asr_words`. Speaker coverage is computed as a **union of intervals** so overlapping observations for the same speaker cannot overstate evidence. Timed word intervals must already be source PCM integer indices.

A word with any review reason is **not automatically a TRANSLATE candidate**. This module does not infer semantic text, singing versus speech, translation policy or TTS instructions. No ASR word timings for a parent cue means A0/A4 must keep that parent in REVIEW rather than treat the empty word list as proof of silence. A2 acoustic model observations independently determine whether protected vocal events are present.

## Local and CI checks

Executed against the isolated module and PR14's `SpeakerTurn` type with Python 3.13.5: `python -m pytest -q tests/test_vocal_word_speakers.py` -> **49 passed**; `python -m compileall -q app tests` -> passed. The repository's full Python/Ruff CI still needs validation on the **exact new PR head** (Python 3.11/3.12; Ubuntu/macOS/Windows). There was no real Whisper, CAM++, native Swift or audio-model inference in this test run.

## Next dependency

A0 alone eventually normalizes PersoDub `app/scripts/whisper_transcribe.py` word timestamps and cue-level CAM++ labels into source samples with reliable cue provenance. The existing CAM++ backend labels ASR cues, **not independently detected speaker turns**. Actual cross-talk and speaker-boundary quality still require a separately qualified source of diarization turns and an independent evaluation corpus. No production pipeline wiring is included in this PR.
