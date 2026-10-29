# Align ASR phrases and acoustic observations without damaging vocal demonstrations

**Experimental, model-free adapter.** Requires the `vocal_policy` from draft PR #6 and `vocal_decisions` schema v1 from PR #1. No raw audio is decoded here. The input is assumed to have authoritative **integer PCM sample indices**; ingest must separately prove the mapping to source-video PTS.

## Why another step is necessary

ASR often returns whole phrases, while inaSpeechSegmenter, CLAP and other acoustic detectors may emit a different set of time windows. Splitting one ASR phrase at every detector boundary and copying its full text into each fragment would duplicate TTS, distort speech and possibly overwrite the attack of a sustained vowel.

`app.vocal_align.align_observations()` builds the input required by `app.vocal_policy.select_vocal_decisions()` without splitting or duplicating any ASR phrase. The two components remain separate: **alignment records evidence; policy decides whether to translate.**

- Every acoustic track must cover the entire decoded stream with ordered, non-overlapping `[start_sample, end_sample)` intervals. Missing windows or unknown labels **fail**, not silently filled with `speech`.
- ASR phrases must be ordered and non-overlapping. Gaps are allowed; a gap is **not** assumed to contain silence.
- An ASR phrase is an **atomic** decision window. If any acoustic model changes class *at any point* within that phrase, that model's vote becomes `uncertain` for the whole phrase; policy therefore returns `REVIEW`. This deliberately sacrifices translation coverage to avoid duplicating a sentence or truncating the onset/offset of singing.
- Adjacent acoustic windows of the **same** class are merged before assessing phrase uniformity; harmless technical chunk boundaries do not cause false `REVIEW`.
- Between ASR phrases, gaps are split at every acoustic change boundary. If acoustic votes indicate protected sounds without ASR, policy can emit `PRESERVE`. Speech votes without ASR stay `REVIEW`.
- At no point does the aligner choose `TRANSLATE`, produce `MIXED`, resample, time-stretch, use floating seconds or modify PCM. All outputs are passed to the unchanged schema-v1/policy validator.
- IDs in `model_revisions` and `acoustic_tracks` must match exactly. This checks **shape**, not whether a reported ID corresponds to an actually independent model. That trust boundary belongs to the model runner.

## Input example

```json
{
  "schema_version": 1,
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "pcm_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "sample_rate": 48000,
  "total_samples": 144000,
  "model_revisions": {"ina": "pinned-ina", "clap": "pinned-clap"},
  "asr_segments": [
    {"start_sample": 0, "end_sample": 96000, "text": "Jetzt singen wir ein A.", "language": "de", "speaker_id": "S0"}
  ],
  "acoustic_tracks": {
    "ina": [
      {"start_sample": 0, "end_sample": 72000, "label": "speech"},
      {"start_sample": 72000, "end_sample": 144000, "label": "vocal"}
    ],
    "clap": [
      {"start_sample": 0, "end_sample": 96000, "label": "speech"},
      {"start_sample": 96000, "end_sample": 144000, "label": "vocal"}
    ]
  }
}
```

In this example one acoustic model detects vocal activity **inside** the ASR phrase. Alignment emits a single 0–96000 ASR window with an `uncertain` vote (safe outcome: `REVIEW`), then one 96000–144000 no-ASR vocal window (safe outcome: `PRESERVE`). The full German ASR phrase is never repeated or partially synthesized.

## Reproducible CLI

```bash
python -m app.vocal_align --source asr-and-acoustic-tracks.json > aligned-observations.json
python -m app.vocal_policy --observations aligned-observations.json > decisions.json
```

Both tools read JSON and print JSON; they do not download weights or invoke external APIs. Bad input exits nonzero. All time windows must be referred to **the same decoded original PCM bytes**, with SHA-256 values filled from the separate ingest pipeline.

## Tests and remaining boundary

```bash
python -m pytest --noconftest tests/test_vocal_decisions.py tests/test_vocal_policy.py tests/test_vocal_align.py -q
```

The tests intentionally include a **one-sample** vocal change inside an ASR phrase, overlapping/gapped detector windows, missing ASR, multiple languages, extremely large integer sample offsets and a CLI round-trip. No trained detector or speaker-identification model has been evaluated. Calibrate on held-out recordings with independently verified onset/offset labels and report both **wrongly translated vocal samples** and **speech recall** before any automatic dubbing.
