# A3-3 - local Whisper/CAM++ cue to decoded PCM observation bridge

**Draft / model-free.** This feature is stacked on [A3-2 PR #15](https://github.com/Patiupinas/PersoDub/pull/15), which is stacked on [A3 phrase grouping PR #14](https://github.com/Patiupinas/PersoDub/pull/14). WhisperNotes remains **read-only source-code reference**, not a runtime dependency or a source of mandatory session JSON.

## Verified existing input path

- `app/scripts/whisper_transcribe.py:_cues_from()` returns local faster-whisper ASR cues: `{"start":0.1,"end":0.4,"text":"Hello world","words":[{"start":0.1,"end":0.2,"word":" Hello"}, ...]}`. The worker **rounds start/end and word offsets to 3 decimal places**, i.e. milliseconds. `app/stt_local.py:transcribe_local(..., word_timestamps=True)` returns these local cues and does not itself bind them to a canonical source-video PCM SHA.
- `app/diar_campplus_client.py:diarize()` **copies** these cues and adds `{"speaker":"SPK0"}`. Its CAM++ embedding model operates on the **existing ASR cue intervals**, not separately estimated diarization turns.
- `app/text/srt.py:clamp_cues()` can shorten a cue's end at the video duration without modifying `words`; in this case the bridge rejects any word outside its clamped parent instead of quietly overwriting sample boundaries.

The new `app/vocal_local_observations.py` is a **pure-data projection** taking the exact dictionaries above. It does not load local Whisper/CAM++ models, call Swift/WhisperNotes, translate, synthesize, or make an acoustic vocal/speech decision.

## API and clock semantics

```python
from app.vocal_local_observations import normalize_local_whisper_cues

observations = normalize_local_whisper_cues(
    existing_worker_cues_with_optional_campplus_labels,
    source_language="de",
    sample_rate=48000,
    total_samples=480000,
    source_offset_samples=0,
)
```

Every numeric time input **must be an integer or floating value of whole milliseconds**, as emitted by the pinned worker. It must be finite and non-negative. Input source offset is explicitly required as an **integer frame index**, relative to the canonical decoded source PCM, to support excerpts without guessing the start time. These parameters must be supplied by a separately verified A0 ingest mapping; this module neither computes nor proves source-video PTS alignment.

Seconds are handled with `Decimal(str(seconds))`, then converted to source frame indices with integer `floor(start*sample_rate)` and `ceil(end*sample_rate)`. At 44.1 kHz, the interval `[0.001,0.002)` seconds maps conservatively to `[44,89)` frames. The conversion is deterministic, including large integer source offsets beyond `2**53`. This **preserves millisecond observation resolution**, it does not restore physical boundaries lost by worker rounding.

Output is an ordered immutable tuple of `LocalCueObservation` with deterministic `cue_id`, literal ASR text, optional `speaker_candidate`, `speaker_evidence`, exact source PCM indices, tuple of `TimedWord` from PR #15, and explicit `review_reasons`. Original provider word text (including meaningful leading spaces), speaker label and word IDs are never synthesized or changed. Input dictionaries are not modified.

## REVIEW reasons and evidence boundaries

- `cue_level_speaker_not_independent`: a present CAM++ `speaker` is not independent diarization-turn evidence. **Every such cue requires review** pending a verified independent source of speaker turns.
- `no_speaker_evidence`: missing CAM++ label.
- `word_timestamps_unavailable`: no real word spans in the worker output. Long text is **not** interpolated into invented words.
- `word_text_mismatch`: the literal joined words do not reconstruct the cue transcript after whitespace normalization. Both stay unchanged.
- `estimated_word_timing`: explicit estimated word-span provenance. A model-supplied timestamp is not verified human ground truth, even when the `is_estimated` flag is false.
- `overlapping_word_timestamps`: overlapping words within a cue.
- `overlapping_asr_cues`: multiple original Whisper cues overlap; each affected cue is preserved and flagged.
- `language_not_approved_for_v1_translation`: detected `es` (future input scope) or `und` (undetermined). Only `de` and `en` are currently supported by the original decision schema v1.

Malformed, out-of-range, non-finite or unquantized timing, inconsistent cue/word intervals, missing text, unsupported fields and invalid sample provenance raise `LocalCueProjectionError`. Empty input produces an empty tuple, **not a classification of the source as silent**.

**A3 observation != A4 permission to translate.** A2 acoustic observations, A4 speech votes, source-PMC protection, human override and A8 independent quality testing determine which portions may be synthesized. Even a "SPK0" label and complete word spans do not authorize TTS.

## Test evidence and remaining integration

- macOS Apple Silicon, Python 3.11.16, scratch clone of PersoDub at `a7d2ae361644b200f76b2b3b520325c8e9ec5753`: **133 focused A3 tests passed** (phrase 24 + word attribution 51 + this bridge 58); Ruff 0.16.6 on new files PASS; `compileall` PASS; `git diff --check` PASS. No test-data or model downloads; only temporary Python test tooling.
- Real `_cues_from` and `clamp_cues` helper functions are exercised with **synthetic data**; local audio inference is not.
- The existing `app/pipeline.py` is unchanged. A0 still needs an opt-in ingestion path establishing input video PTS to decoded-source-PCM offsets/hashes, and real `transcribe_local(...word_timestamps=True)` + `diarize()` model execution under a qualified environment. A2 vocal-demo models and A8 real acoustic gold are **not** provided here.
