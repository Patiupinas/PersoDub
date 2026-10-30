# Selective vocal dubbing: sample-accurate decision contract (v1)

**Status: opt-in, not connected to production PersoDub.** This schema establishes
which portions of a decoded audio stream are safe to translate and which must
remain original. It does **not** classify audio or modify any media.

## Source of truth

- `source_sha256`: lowercase SHA-256 of the original container file.
- `pcm_sha256`: lowercase SHA-256 of the specific decoded PCM stream.
- `sample_rate`: positive PCM frame rate, not the video's timestamp rate.
- `total_samples`: count of decoded PCM **frames** (one frame includes all
  audio channels), not byte count and not a floating-point duration.
- `[start_sample, end_sample)`: absolute frame indices in the chosen decoded
  stream, starting at zero. Adjacent intervals meet at the same integer index.
- **Every frame must be covered by exactly one leaf decision**. Unknown audio
  is explicitly `REVIEW`; an unlabeled gap or overlap rejects the manifest.
- The ingest layer must maintain the separate exact mapping between decoded
  PCM sample zero and source video PTS. This validator cannot infer it.

## Actions

| Action | Contract | Output handling (future integration) |
| --- | --- | --- |
| `TRANSLATE` | Requires `source_language` (`de`/`en`) and `source_text` | May use local translation and TTS; source-language leakage gate applies |
| `PRESERVE` | No synthesis or suppression | Must use untouched *original decoded PCM*, not separated `vocals.wav` |
| `REVIEW` | Requires an explicit `reason` | Leave original audio in place until a human resolves it |
| `MIXED` | Requires at least two adjacent, fully covering child leaf spans | Only its children are actionable; no parent-wide TTS |

A `MIXED` child cannot be another `MIXED` in v1. Use a single flattened level of
leaf decisions. Leaf segments cannot have `children` (even empty).

The optional `human_override` has `previous_action` and a nonempty `reason`;
`action` is the **single effective action**. An override cannot be identical
to the effective action. IDs are unique across both parents and children.
Optional `confidence` must be finite within [0, 1]. `model_revisions` is an
optional mapping from provider name to nonempty revision ID.

## Example

```json
{
  "schema_version": 1,
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "pcm_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "sample_rate": 48000,
  "total_samples": 144000,
  "model_revisions": {"classifier": "example-only"},
  "segments": [
    {
      "segment_id": "example-mixed",
      "start_sample": 0,
      "end_sample": 144000,
      "action": "MIXED",
      "children": [
        {
          "segment_id": "speech-1",
          "start_sample": 0,
          "end_sample": 48000,
          "action": "TRANSLATE",
          "source_language": "de",
          "source_text": "Jetzt ein offenes A."
        },
        {
          "segment_id": "vocal-1",
          "start_sample": 48000,
          "end_sample": 96000,
          "action": "PRESERVE",
          "reason": "sustained sung vowel"
        },
        {
          "segment_id": "speech-2",
          "start_sample": 96000,
          "end_sample": 144000,
          "action": "REVIEW",
          "reason": "unclear speech/vocal transition"
        }
      ]
    }
  ]
}
```

```python
import json
from app.vocal_decisions import parse_decision_manifest

with open("decisions.json", encoding="utf-8") as file:
    decision = parse_decision_manifest(json.load(file))

for span in decision.spans:  # immutable, ordered, only leaf actions
    print(span.action, span.start_sample, span.end_sample)
```

**Fail-closed:** an invalid manifest raises `DecisionValidationError`. A future
mixer must not continue using a partially validated plan, silently sort spans,
repair reversed boundaries, or default uncovered audio to TTS. As a separate
safety gate, mixer integration must check the actual audio stream against the
stated PCM hash and verify the unchanged PCM bytes for `PRESERVE` spans.

## What this PR does not prove

Validation checks the shape and logical partition of metadata. It cannot
prove that sound was correctly classified, that hashes match actual media,
that video PTS maps correctly, or that TTS/output preserves sound. Those are
separate benchmark, ingest, and mixer tasks.

No neural model, GPU, cloud API, or commercial footage is required for these
unit tests. Existing standard PersoDub behavior is untouched.
