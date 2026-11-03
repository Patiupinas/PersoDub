# Conservative vocal-vs-speech decision policy (prototype)

**Status:** model-free, opt-in adapter contract; not connected to PersoDub ASR/translation/TTS. This module never classifies sound itself. The `vocal_decisions` schema-v1 validator remains the authoritative timeline contract.

## Purpose

A vocal lecture includes instructional speech, singing examples, sustained vowels, breath exercises, overlap and silence. An ASR transcript **is not proof** of ordinary speech; Whisper can also emit words during singing. We need independent acoustic evidence before replacing the original audio.

`app.vocal_policy.select_vocal_decisions(observations)` takes already-aligned acoustic votes plus ASR text for **complete, non-overlapping integer PCM windows**. It outputs a valid schema-v1 `decisions.json`, whose intervals are permitted to pass into the independent PCM assembler and benchmark.

## Default rules (conservative)

- **TRANSLATE** only when non-empty DE or EN ASR text exists and at least two **different declared acoustic model IDs** unanimously vote `speech`. Any conflicting or uncertain vote prohibits automatic translation.
- **PRESERVE** only when ASR is absent and non-empty acoustic votes all indicate `vocal`, `music`, `breath` or `silence`. The source PCM is protected.
- **REVIEW** for incomplete evidence, disagreement, acoustic uncertainty, missing ASR, ambiguous language and simultaneous ASR plus detected singing. Preserve the source PCM until the reviewer resolves the segment.
- Unknown labels, duplicate acoustic model IDs, unregistered model revisions, malformed metadata, gaps/overlaps and unsupported field names fail before the manifest can be used. Votes are never silently dropped.
- The policy never overrides a user's manual decision. A reviewer should edit/override the resulting schema-v1 manifest separately with traceable provenance.

**Important limits:** two model IDs are not guaranteed statistically independent, two models can make the same mistake, and `PRESERVE` confidence is not established. No thresholds are calibrated yet. This is a safe *default rule*, not evidence of a reliable classifier. Only held-out manually annotated DE/EN singing samples can validate actual safety.

## JSON input contract

```json
{
  "schema_version": 1,
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "pcm_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "sample_rate": 48000,
  "total_samples": 96000,
  "model_revisions": {"ina": "ina-v1", "clap": "clap-v1"},
  "windows": [
    {
      "start_sample": 0,
      "end_sample": 48000,
      "asr": {"text": "Jetzt probieren wir ein A.", "language": "de", "speaker_id": "S0"},
      "votes": [{"model_id": "ina", "label": "speech"}, {"model_id": "clap", "label": "speech"}]
    },
    {
      "start_sample": 48000,
      "end_sample": 96000,
      "asr": null,
      "votes": [{"model_id": "ina", "label": "vocal"}, {"model_id": "clap", "label": "vocal"}]
    }
  ]
}
```

```bash
python -m app.vocal_policy --observations aligned-observations.json > decisions.json
```

The input **must already be divided at all acoustic/ASR change boundaries**; this module does not map floating-point speech timestamps, slice audio, merge model outputs or infer source-video PTS. That alignment/ingest step must be separately verified, especially around phonation attacks and mixed overlapping voices. A model's class `music` may also include instrumental accompaniment; treating the whole interval as PRESERVE is the safe fallback.

## Tests

```bash
python -m pytest --noconftest tests/test_vocal_decisions.py tests/test_vocal_policy.py -q
```

No model download, GPU, cloud API or media files are needed. Test the actual detectors later on split-by-speaker RAVDESS, VocalSet, German voice exercises and representative held-out masterclasses; use sample-weighted benchmark metrics and human review of false-TRANSLATE events. Never treat this rule as permission to clone/distribute a third-party lecturer's voice.
