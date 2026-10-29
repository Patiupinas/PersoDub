# Vocal dubbing safety benchmark (model-free scorer)

**Status:** independent, opt-in pure-Python evaluator. It compares two schema-v1 decision manifests over the same decoded PCM timeline; no audio models, WAV files, datasets, network access or GPU are required.

## Inputs

- **Gold:** manually annotated `decisions.json` containing the complete timeline, with `TRANSLATE` (instructional speech), `PRESERVE` (singing/exercises/other must-keep sounds), or `REVIEW` (genuinely uncertain). `MIXED` parents must contain valid non-overlapping children and are automatically flattened by the v1 parser.
- **Prediction:** another valid `decisions.json` from a candidate classifier. Both must share the exact `source_sha256`, `pcm_sha256`, `sample_rate`, and `total_samples`.
- Labels are scored **per PCM sample frame**, not per subtitle word, ASR token, model chunk or SRT line. Boundaries are integer `start_sample` and `end_sample` in the *same* decoded audio stream.
- Gold annotations should be produced independently of the model being tested, should include difficult DE/EN speech-to-vocal transitions, and must be split by **speaker/lecture** before calibration and holdout scoring. Merely synthesizing labels from a model's own decisions is not a valid gold standard.

## CLI

```bash
python -m app.vocal_benchmark --gold reference.decisions.json --pred candidate.decisions.json
python -m app.vocal_benchmark --gold reference.decisions.json --pred candidate.decisions.json --fail-on-unsafe
```

The first invocation prints a deterministic JSON report, exit `0` on structurally valid inputs even if the model made unsafe predictions. The `--fail-on-unsafe` option exits `1` if *any* gold `PRESERVE` or `REVIEW` frame is predicted `TRANSLATE`; if the gold set lacks protected segments, it exits `2` as **inconclusive**. Invalid/mismatched manifests also exit `2`. This is a guard for evaluation, **not** an audio-integrity test.

## Reported measurements

- `confusion_samples[gold][predicted]`: full 3x3 confusion matrix, in **PCM sample frames**. Matrix counts sum exactly to `total_samples`.
- `vocal_preservation.gold_protected_samples`: duration of gold `PRESERVE` examples, including singing/growl/vocalization.
- `vocal_preservation.wrongly_translated_samples`: sample frames where a gold `PRESERVE` example was incorrectly assigned `TRANSLATE`.
- `vocal_preservation.affected_gold_segments`: number of distinct manually marked preserved events touched by at least one translation frame. Important because a one-sample cut into the attack of a vocal can be audible even when duration-based error percentage is tiny.
- `vocal_preservation.zero_corrupted_vocal_segments`: `true` only if there are protected examples and none were marked for translation. **`null` when the test set contains none**, rather than reporting a meaningless PASS.
- `ambiguous_safety`: analogous measurements for genuinely uncertain **gold REVIEW** intervals; separately tracks unsafe translation of uncertain sound.
- `speech_utility.recall`: fraction of gold instructional speech actually marked for translation. A model that assigns `REVIEW` to *everything* scores zero recall even if no vocal example is damaged.
- `speech_utility.precision`: fraction of all predicted `TRANSLATE` sample frames that are truly gold instructional speech.
- `predicted_review.fraction_of_total`: explicitly exposes conservative fallback volume. High review share can protect vocals but produce an unusably untranslated course.
- All fractions are `null` where the denominator is zero; these are not silently set to 0% or 100%.
- `predicted_model_revisions` is recorded from the supplied prediction manifest, but not independently authenticated.

All reported sample counts are integers. For seconds divide by `sample_rate`; avoid rounding boundaries during scoring.

## Test coverage

```bash
python -m pytest tests/test_vocal_decisions.py tests/test_vocal_benchmark.py -q
```

Synthetic tests cover exact matches, a **single-sample** attack mislabel, misclassification of ambiguous intervals, `REVIEW`-everything failure of utility, absence of protected or translated examples, mismatched hashes/timeline, split vocal events, nested MIXED extraction, gaps and overlaps, 1,500 adjacent intervals, and CLI strict/fail behavior.

## What this cannot prove

- Reference labels may themselves be incomplete/incorrect; a 0-error score on biased or tiny gold is not evidence that live classes such as twang, scream, growl, falsetto, short vowels and overlapping singing are handled.
- Safe *decisions* do not prove untouched output **audio bytes**. Use [PCM assembler integrity verification](vocal-pcm.md) in addition to classification scoring.
- This scorer cannot measure translation meaning, Russian TTS voice similarity, background music mixing, or final MP4 synchronization.
- The success threshold of **zero automatically translated protected exercises on holdout** is a project acceptance target, not an achieved real-data result. Report dataset composition, per-speaker split, confidence and the actual `REVIEW` share alongside the score.
