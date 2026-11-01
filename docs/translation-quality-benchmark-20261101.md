# PersoDub P1-B: source-bound automatic translation quality triage

**Date:** 2026-11-01 (Europe/Madrid). **Machine:** Raymonds-Laptop.local, Mac M1 Max, arm64.
**Work branch:** `feature/vocal-translation-qe-20261101`, based on local tree of Draft PR #35.
This is read-only research QA, not a translation pipeline replacement or product acceptance.

## What is now implemented

- `python -m benchmarks.persodub.translation_quality` reads English `original.srt` and Russian `translated.srt` without modifying them.
- Dynamic-programming monotone alignment compares 1:1, 1:N and N:1 cue groups using the source time clock. It also reports unmatched source and translation cues. A naive index zip and an overlapping-component merge were both rejected by regression tests.
- Independent `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` embeddings provide a **cross-language semantic-similarity proxy**, not a calibrated translation-adequacy percentage. Actual model commit: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. One selected model was downloaded to the existing Hugging Face cache for this run; weights are not committed or bundled.
- Optional `--scorer comet --comet-checkpoint /path/to/licensed/model.ckpt` supports a separately available local reference-free COMET model. No COMET inference was run for this report; the COMETKiwi model requires licensing/access acknowledgement on Hugging Face.
- Output contains time spans, original and translated text, ranked low-similarity pairs, heuristic numeral flags, data/model identities, and explicit `semantic_quality_certified=false`.
- `benchmarks.persodub.runner` can ingest a report using `quality_report` in a `translation` case. The input source and translation SHA-256 must match; otherwise it produces ERROR. Even with a model score, the benchmark case is only `OBSERVED`, not a semantic PASS.

## Real four-minute result, on copied jobs

*Breath Control for TOTAL Beginners*, original completed job `a45f8233` and owner-initiated redub `34d7c248`, 234.684 seconds.

| Measurement | 2026-10-31 original job | 2026-11-01 redub |
| --- | ---: | ---: |
| Source cue count | 32 | 31 |
| Translated cue count | 32 | 32 |
| Aligned scored groups | 32 | 27 |
| Unpaired source/translation groups | 0 / 0 | 0 / 0 |
| Mean multilingual similarity | 0.663325 | 0.660856 |
| Lowest aligned similarity | 0.121762 | 0.406741 |
| Status | OBSERVED | OBSERVED |

**Crucial A/B finding:** both Russian `translated.srt` files have identical SHA-256 `f489f56ff1ac336363f754ba5c5ed8cc5d038aef38566f59070f9bee9a9ff99c`. English source SRT hashes are different: original `94ce43a7...`, redub `92acb7b7...`. Consequently **these two averages are not a valid translation-quality comparison**. The text has not changed; the small score change arises from different English transcript segmentation. Future head-to-head tests must use a single frozen source transcript and the same alignment scheme. This was additionally verified by re-running the redub candidate with the original English SRT as a frozen source: the resulting 32 scores reproduce the baseline mean **0.663325 exactly**; see local `redub-fixed-source.json`.

The redub's lowest scored span is around 74.78-81.68 s, similarity 0.406741; other low-ranking spans include ~150-167 s and ~166-188 s. These are **review candidates**, not automatically verified errors. A perfectly reasonable short paraphrase around 130.94-131.82 s received just 0.45411, demonstrating why numerical thresholds must not be called accuracy without an independent oracle.

Separate timing and clipping QA remains in `app.dub_quality_audit`; neither report measures how the translated words are pronounced in the rendered TTS audio.

## Reproduce on the Mac

The model-run Python environment with Torch/Transformers already exists at `~/.persodub-dev-kit/engines_venv/bin/python`. The core app environment does **not** acquire these heavy dependencies.

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-translation-qe-20261101
~/.persodub-dev-kit/engines_venv/bin/python -m benchmarks.persodub.translation_quality \
  --source /path/to/job/original.srt \
  --translation /path/to/job/translated.srt \
  --out /path/to/local/translation-quality.json
```

The model is now cached on this Mac. On a fresh machine, `--allow-download` explicitly authorizes downloading only this selected model.

To re-run the two real cases:

```sh
sh ~/Documents/PersoDub-Research/reports/p1-translation-qe-20261101/run.sh
python -m benchmarks.persodub.runner \
  --manifest ~/Documents/PersoDub-Research/reports/p1-translation-qe-20261101/manifest.json \
  --out ~/Documents/PersoDub-Research/reports/p1-translation-qe-20261101/chain.json
```

The local report folder contains `2026-10-31.json`, `2026-11-01.json`, `manifest.json`, and `chain.json`. These include local/private project text and are kept outside Git. No user video, translated text, weights or audio are committed.

## Verification and next independent decision

Mac verification: 22 focused translation/benchmark tests PASSED; complete Python suite 2,596 passed / 5 skipped; UI 1,143 passed; desktop 713 passed; Ruff, Python compile, inline JS and Git diff check PASS. Scores use actual local model inference, not mocks. The metric has **no calibrated good/bad cutoff**, no independent bilingual human ratings, no COMETKiwi run and no acoustic Russian ASR readback yet. Do not infer that 0.66 means 66% faithful translation.

**One next action:** freeze independently bilingual-reviewed EN/RU adequacy labels for the five lowest-ranked, source-bound intervals, including one correct paraphrase as a negative control; use those to test whether COMET or the local neural proxy really discriminates genuine meaning errors before turning its scores into an automatic gate.
