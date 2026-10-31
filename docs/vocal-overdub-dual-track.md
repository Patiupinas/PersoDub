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

**UI:** The desktop New project form does not yet expose an Overdub toggle. This is intentionally an opt-in backend and post-export function until the A1/A4 source event classifier delivers independently verified actions. It does not affect cloud Perso dubbing or the default local export.

## Verification

- Synthetic PCM tests assert original speech attenuation, audible translated voice, true original restoration on exercises, cosine transitions, exact source clock, padding, bounded memory, no gain-summation clipping and rejection of stale/incomplete plans.
- Actual FFmpeg/ffprobe tests create an MP4 with two playable selectable audio streams and correct dispositions.
- Existing Qwen assembly and pipeline tests assert that `replace` mode behaves as before.
- The real current project can be re-exported without downloading any models or re-running TTS.

No media, human gold labels, commercial audio, model weights or GitHub Actions are introduced in the branch.
