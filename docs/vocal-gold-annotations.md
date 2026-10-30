# A1: reviewed event annotations to canonical vocal gold

**Dependency:** this Draft PR is stacked on [PR #1](https://github.com/Patiupinas/PersoDub/pull/1) (canonical `app/vocal_decisions.py` parser), and deliberately does **not** copy its validator. Companion protocol: [A1_GOLD_LABELING_PROTOCOL.md](https://github.com/Patiupinas/misc/blob/design/vocal-dubbing-agent-architecture-20261030/vocal-lecture-dubbing/A1_GOLD_LABELING_PROTOCOL.md).

## Why this component exists

The canonical benchmark [PR #3](https://github.com/Patiupinas/PersoDub/pull/3) scores `TRANSLATE/PRESERVE/REVIEW` decisions by PCM frame. However, its `PRESERVE` bucket contains both protected vocal exercises and ordinary untranslatable silence/background sounds. A1 annotations record the underlying **human event type**, and the compiler supplies both (1) a valid canonical decision manifest for the existing scorer, and (2) a separate event-type summary so vocal demonstrations are not confused with all preserved audio.

This code **does not certify** that two listeners independently reviewed the annotation, that a text transcript is correct, or that hashes actually match any supplied media bytes. Those are A1/A8 review and ingest responsibilities. No model or recording is opened by this pure-data compiler.

## Accepted v1 contract

```json
{
  "schema_version": 1,
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "pcm_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "sample_rate": 48000,
  "total_samples": 144000,
  "source_revision": "decoded-pcm-v1",
  "annotation_revision": "human-adjudicated-v1",
  "events": [
    {
      "event_id": "human_001",
      "start_sample": 0,
      "end_sample": 48000,
      "event_type": "explanation",
      "speaker_id": "SPK0",
      "source_language": "de",
      "source_text": "Wir beginnen mit der Übung.",
      "reason": "Reviewed explanatory speech"
    },
    {
      "event_id": "human_002",
      "start_sample": 48000,
      "end_sample": 96000,
      "event_type": "vocal_demo",
      "speaker_id": "SPK0",
      "reason": "Reviewed sustained vowel"
    },
    {
      "event_id": "human_003",
      "start_sample": 96000,
      "end_sample": 144000,
      "event_type": "non_target",
      "reason": "Reviewed background only"
    }
  ]
}
```

This is a **synthetic schema example**, not a real adjudicated source recording. Every event has a stable unique `event_id`, an explanatory `reason`, a half-open integer `[start_sample,end_sample)` span and one `event_type`. Events cover **all** original decoded PCM frames in order without gaps or overlap. `source_revision` and `annotation_revision` refer to externally stored provenance, not to a model.

| Human event_type | Canonical action | Notes |
| --- | --- | --- |
| `explanation` | `TRANSLATE` | **Requires verified actual EN/DE source text** and explicit source language under schema v1 |
| `vocal_demo` | `PRESERVE` | Do not invent vocal syllables/captions |
| `non_target` | `PRESERVE` | Counts separately from vocal demonstrations |
| `speech_vocal_overlap` | `REVIEW` | Does not authorize speech replacement |
| `uncertain` | `REVIEW` | Adjudication/review remains explicit |

Future `es` source-language labels may remain in research annotation archives, but cannot be converted to v1 decision gold until the DE/EN-only policy is extended. **No silent ES -> und mapping.** If a human-labelled explanation has no literal, verified transcription, the compiler fails rather than creating fake source text.

## CLI

```bash
python -m app.vocal_gold_annotations \
  --annotations reviewed.events.json \
  --manifest-out reviewed.decisions.json \
  --summary-out reviewed.event-summary.json

python -m app.vocal_benchmark \
  --gold reviewed.decisions.json \
  --pred candidate.decisions.json \
  --fail-on-unsafe
```

The second command is supplied by the already-existing [benchmark PR #3](https://github.com/Patiupinas/PersoDub/pull/3). It is **not** a dependency of this code PR. The first command writes derived files only after validating the input. The two outputs must be distinct from each other and from the original annotation file. Keep the original human event file as the authoritative record.

The summary contains `event_counts`, `event_samples`, `vocal_demo_events` and `vocal_demo_samples` with exact integer sample counts. It is descriptive; full event-type-specific incorrect-translation metrics are A8's independent task.

## Verification

Focused, synthetic local tests on Python 3.13.5: **39 passed with a temporary local minimal stand-in for the canonical validator**. That stub is **not included in this PR**; authoritative compatibility will be checked by GitHub's normal Python 3.11/Windows/macOS/Linux CI against the real `vocal_decisions.py` from PR #1. No real human-labeled audio, source SHA verification, ASR, TTS or GPU work was performed.

No main branch changes or automatic merge.
