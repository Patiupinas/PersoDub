# PersoDub: opt-in dual-track Overdub

**Status: executable backend pilot; no automatic A4 event classification.** The default replacement dub is unchanged.

## Listening behavior

An Overdub export contains two selectable audio streams in one MP4:

1. **Overdub** (default): the original soundtrack plus synthesized translation, with smooth event-aware gain envelopes.
2. **Original**: a separate copy of the original video's first audio stream, without overdub gain changes.

The original audio is never deleted. Both spoken languages are audible during `TRANSLATE` events; during `PRESERVE` and `REVIEW` the original audio is primary and synthesized words are fully off outside the crossfades.

Default levels:

| Event action | Original | Synthesized voice |
| --- | ---: | ---: |
| `TRANSLATE` (spoken explanation) | -16 dB | -2 dB |
| `PRESERVE` (singing/exercise/laughter etc.) | 0 dB | Muted |
| `REVIEW` (unclassified/awaiting decision) | 0 dB | Muted |

Short (up to 50 ms) TTS/sep audio tails beyond the source video are trimmed; longer mismatches stop the export. A shorter soundtrack is silence-padded to the video duration at extraction.

The crossfade is **300 ms raised-cosine**, centered on each event boundary, shortened for very short events. The gain sum never exceeds unity, so the mixer does not introduce summation clipping. The `PRESERVE` and `REVIEW` source samples outside these transitions are bit-identical to the original 48 kHz PCM.

### Authority and event clock

This implementation consumes only **explicit** actions; it does not translate raw Whisper, INA, SMAD, AST, MOSS or emotion2vec tags into permissions.

`overdub_events.json` contract:

```json
{
  "schema_version": 1,
  "sample_rate": 48000,
  "total_frames": 144000,
  "source_wav_sha256": "<64 hex digits from the exact decoded source WAV>",
  "events": [
    {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
    {"start_frame": 48000, "end_frame": 96000, "action": "PRESERVE"},
    {"start_frame": 96000, "end_frame": 144000, "action": "REVIEW"}
  ]
}
```

The events must cover the exact PCM source from sample 0 through the final frame, with no gaps/overlaps. The SHA-256 binds the plan to the exact decoded source WAV, so accidentally using an annotation for another video, sample rate or version of a trim is rejected. All unknown content should remain `REVIEW`. This schema is a source-bound **action plan**, not by itself proof of independent human review; approval provenance remains owned by the eventual A1/A4 compiler.

## Use 1: Export an existing finished local Qwen job (no new TTS)

The job must retain `input.mp4`, `lines.json` and its `qwen_line_0.wav`, `qwen_line_1.wav`, etc. The exporter reads the original per-line start timestamps and gain values to rebuild just the translated-voice layer. It does not reuse `qwen_dub_48k.wav` because that file already includes the separated background and would double the source audio.

Create a source-bound plan template:

```sh
python -m app.vocal_overdub_export prepare \
  --video /path/to/job/input.mp4 \
  --work-dir /path/to/job \
  --events /path/to/job/overdub_events.json
```

The initial template contains a single `REVIEW` event and **no translation permissions**. Split into verified speech/performative exercise events, converting times to integer 48 kHz source frames. A 1.250 s boundary is frame `60000`.

After the action partition is reviewed:

```sh
python -m app.vocal_overdub_export export \
  --video /path/to/job/input.mp4 \
  --work-dir /path/to/job \
  --events /path/to/job/overdub_events.json \
  --output /path/to/job/finished-overdub.mp4 \
  --original-speech-db -16 \
  --dub-speech-db -2 \
  --fade-ms 300
```

The exporter writes the second MP4 without replacing `finished.mp4`. It also writes `finished-overdub.mp4.overdub.json` with the source, dub-layer, event plan and resulting WAV SHA-256 plus applied levels and frame counts.

## Use 2: Run the Qwen pipeline in Overdub mode

The local Python API now supports:

```python
from app.pipeline import run_dub

result = run_dub(
    video_path="/path/to/input.mp4",
    out_path="/path/to/finished-overdub.mp4",
    audio_mode="overdub",
    overdub_event_plan_path="/path/to/overdub_events.json",
)
```

The exact source PCM and plan are checked before separation, transcription, translation or synthesis. The mode uses the existing `place_lines` anti-overlap and loudness matching, but places TTS over silence. The final stage combines it with the decoded original soundtrack and muxes both selectable tracks. The existing `leakage_gate` remains between speech synthesis and original audio overlay.

## New review-and-export UI (separate draft PR)

For a finished **local Qwen** project: open **Download**, choose
**Overdub: original + translation**. This opens a dedicated review dialog:

1. **Prepare** automatically decodes the actual source video to 48 kHz stereo,
   hashes it and starts with candidate speech time ranges from the existing
   source-language SRT. Every interval initially has the independent action
   `REVIEW`, never `TRANSLATE`.
2. **Suggest events with AST** is available only when the operator explicitly
   configures a local isolated ML interpreter and the verified cached AST model:
   `PERSODUB_AST_PYTHON=/path/to/audio-ml-python` and
   `PERSODUB_AST_MODEL_DIR=/path/to/pinned/MIT-AST-snapshot`.
   It launches `app.scripts.ast_overdub_observer` with `local_files_only=True`,
   verifies model weights SHA, observes 4 s windows at a 2 s stride and maps them
   to coarse suggestions. The source-original SHA and integer 48 kHz frame
   positions must agree. It never downloads weights, installs new core
   dependencies or changes the A4 action plan by itself.
3. Examine each interval. Use **Apply suggestions** for an explicit first
   pass, change per-row `REVIEW` / `TRANSLATE` / `PRESERVE`, and split
   intervals at a manually chosen second. Applying suggestions does **not**
   check the review confirmation or start any export.
4. Check **I reviewed these intervals**, then export. The API rejects
   unconfirmed actions, incomplete or overlapping intervals, unknown source
   SHA, unsupported jobs, and invalid gain combinations. It writes a new
   immutable approved plan and a separate `finished-overdub*.mp4`.
   The existing dubbed video and original input stay unchanged.

AST results represent **uncalibrated model clues**, not ground-truth event
boundaries. Humming and singing may be misclassified as speech; "vocal exercise"
is still a human-reviewed event decision. Unclassified intervals stay original.
When AST is unavailable, the user can still manually review split and assign
all actions with speech-cue suggestions.

**Scope:** This is an opt-in re-export on the existing finished project's
Download dialog, not a new-project setting. The default local replacement
pipeline and the Perso cloud path remain unchanged. All strings and controls
are available in the desktop UI; new untranslated strings fall back to English
under a non-English UI locale.

## Long-form lessons (hours, not only short videos)

The target use case includes **2-6-hour vocal lessons**, which can mix
explanations, live examples, singing, humming, pauses and unrelated audio.

The first scaling step in this branch:

- AST consumes mono 16 kHz audio as a **stream from FFmpeg**, with a bounded
  four-second window and two-second stride. The earlier hard-coded 30-minute
  limit and full mono intermediate WAV are removed. The source PCM SHA and
  original 48 kHz clock remain the authority.
- Observation-to-suggestion matching is now indexed by sorted window centers
  rather than searching the entire AST timeline for each two-second bin.
  Transcript cue suggestions likewise use merged cue ranges and a sweep.
  Synthetic 6-hour timelines exercise both paths.
- The review UI renders a maximum of **100 editable intervals at a time**.
  The full event partition, manual edits, and global sample indices remain
  intact across pages and in the submitted export plan.
- AST process timeouts scale with video duration instead of always stopping
  at 900 seconds, capped at twelve hours. AST still runs in one HTTP operation;
  this is a *pilot*, not a resumable long-running analysis scheduler.
- Before export, the backend checks room for four 48 kHz stereo PCM copies,
  two potential MP4 copies and a fixed scratch margin. It rejects sources
  beyond the current single-WAV RIFF capacity *before extraction* instead of
  allowing a truncated/corrupt WAV.

**Not yet supported:** source audio requiring more than one standard RIFF WAV
(roughly 6 hours 12 minutes at 48 kHz PCM16 stereo). Multi-chapter decoding,
mixing, source-clock-preserving assembly, and checkpoints for AST analysis are
needed to remove this limit. Synthetic long-clock tests are not equivalent
to actually dubbing and exporting a six-hour recording.

**Critical throughput work remaining:** the full local pipeline still uses
Qwen's `Best of 4` on every translated utterance if that quality mode is
selected. A multi-hour lesson may take far longer than the source duration.
Before calling long-form production ready, classify protected vocal exercises
**before TTS**, synthesize only the speech spans, reuse completed voice lines
and select additional takes based on measured quality rather than routinely
generating four versions. Benchmark `Fast` versus selective retries against
source-voice similarity and completeness; changing the quality policy without
measuring it is not part of this branch.

Release acceptance still needs independent source-bound test videos of
2, 4 and 6 hours, simulated interruptions at every stage, checks of
resumability, peak RSS/disk use, sample-clock drift at section boundaries,
two-track MP4 integrity, duration of synthesis, and translated speech vs.
preserved vocal-exercise correctness.

### Local model replay evidence

On 2026-10-31, the new AST adapter processed 60 s of the previously selected
US Navy Band lesson derivative as 29 four-second windows. It agreed on the
top coarse category with the earlier independent AST implementation in 28/29
windows (small resampling differences). That is **reproducibility**, not
labelled boundary accuracy. The reviewer can inspect and override every model
suggestion; unreviewed model predictions never become a dub decision.


## Verification

- Synthetic PCM tests assert original speech attenuation, audible translated voice, true original restoration on exercises, cosine transitions, exact source clock, padding, bounded memory, no gain-summation clipping and rejection of stale/incomplete plans.
- Actual FFmpeg/ffprobe tests create an MP4 with two playable selectable audio streams and correct dispositions.
- Existing Qwen assembly and pipeline tests assert that `replace` mode behaves as before.
- The real current project can be re-exported without downloading any models or re-running TTS.

No media, human gold labels, commercial audio, model weights or GitHub Actions are introduced in the branch.
