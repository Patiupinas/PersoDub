# PersoDub P1-B: do translation-QA metrics actually detect meaning changes?

**Study date:** 2026-11-01, Europe/Madrid. **Hardware:** Mac M1 Max, arm64. **Source branch:** Draft PR #36, `feature/vocal-translation-qe-20261101`, exact local tree `a751dc594cae91cb54d043203e79ee6e9597e9c4`.

## Question and measured experiment

The existing cross-language MiniLM mean similarity of ~0.66 **does not** mean the translation is 66% correct. Before creating a translation-quality acceptance gate, test whether the metric prefers an evidently faithful RU paraphrase to an intentionally altered RU sentence for the same EN source.

`benchmarks/persodub/fixtures/translation_synthetic_controls_v1.json` contains 20 original, **model-authored**, non-private EN-RU contrastive controls. Each has a plausible faithful translation and one intentionally altered translation. Topics cover negation, vocal exercises, sequence, stress, pitch, tempo, speaker identity, musical modes, numbers and omissions. **These are deterministic software controls, not independently bilingual human-reviewed gold and not held-out product acceptance.** Do not use them to claim accuracy on naturally occurring translation errors.

The same frozen control pairs were scored by:

1. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` using cross-language masked-mean-pooled cosine (prior stage).
2. `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`, bidirectional EN/RU textual entailment (independent diagnostic model, MIT). Symmetric score = min of the two entailment probabilities. It is an NLI model, **not** an MT adequacy model.
3. `Unbabel/wmt20-comet-qe-da`, a purpose-trained, reference-free translation-quality estimator (Apache-2.0), executed in an isolated Python 3.11 COMET environment. This older model is non-gated and its numerical scores may be negative; no 0-1 threshold is assumed.
4. Small deterministic **EN->RU-only** hints for explicit cardinal numbers and ordered major/minor key names, with explainable facts and review flags. Does not judge negation or full meaning.

## Results on the same 20 controlled source pairs

| Diagnostic | Faithful RU ranked above altered RU | Missed control IDs |
| --- | ---: | --- |
| MiniLM embedding | **17 / 20** | s06, s10, s12 |
| Multilingual NLI, symmetric entailment | **16 / 20** | s06, s11, s12, s14 |
| COMET-QE wmt20 | **16 / 20** | s02, s11, s12, s18 |
| Explicit EN/RU number and key checks | **5 discriminative mismatches** | Not a general semantic scorer |
| Embedding rank OR fact hints | **18 / 20**, no false flags on faithful controls | s06, s10 |

The new explicit fact hint caught the `C major, not A minor` vs reversed `ля минор, не до мажор` failure that **all three neural metrics missed**. Russian inflected numerals (`двумя`, `одной`, `четырьмя`) were added to eliminate two false flags on faithful synthetic candidates. These are review hints, not automatic decisions or evidence that natural-language adequacy was measured.

The NLI and COMET alternatives did **not outperform MiniLM** in controlled pairwise ranking. Do not replace the current scoring backend or average the three scores on the basis of this experiment. Numeric scales differ and the control set is both small and synthetic.

## Real-source check

Unchanged original job `a45f8233`, source lesson `Breath Control for TOTAL Beginners`, 234.684 s, source SRT frozen at SHA `94ce43a7...`, target Russian SRT at SHA `f489f56f...`. Source-bound report has **32** aligned groups. These 32 real pairs were also scored by all three models. No translation, source media, original audio, output rendering or user job was modified.

The shared low-scoring example at **145.64-146.72 s** appears to compress a source explanation into a very short Russian statement. MiniLM similarity ~0.122, NLI symmetric entailment ~0.026, COMET-QE ~-1.446. Exact source and translated text are retained only in local reports, not in Git. This is a strong **review candidate**, not ground-truth-confirmed inadequate translation. Other COMET low ranks include ~36-40 s, ~171-181 s, ~116-125 s and ~189-195 s. Source ASR itself is not independent human gold; some low scores can arise from the English transcript or alignment.

**Separate deliverables, all kept on the Mac outside Git**:

- `~/Documents/PersoDub-Research/reports/p1-translation-controls-20261101/controls-embedding-and-real.json`: original embedding-only pilot
- `.../controls-nli-and-real.json`: actual embedding + independent NLI + fact hints, with all 32 real pairs
- `.../controls-comet-and-real.json`: measured COMET-QE scores plus comparisons
- `.../review_pack.csv`: eight real-source low-score intervals, side-by-side EN/RU text, three model scores and empty independent-review fields. No human ratings have been invented.
- Original two-source benchmark remains in `~/Documents/PersoDub-Research/reports/p1-translation-qe-20261101`.

## Reproduction and dependencies

Core app dependencies remain unchanged. The cached MiniLM encoder and NLI model run from `~/.persodub-dev-kit/engines_venv/bin/python`. NLI model revision: `0a71e92a985b6e1ad1828cf67ce9c459639c1dca`. MiniLM revision: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-translation-controls-20261101
~/.persodub-dev-kit/engines_venv/bin/python \
  -m benchmarks.persodub.translation_controls \
  --controls benchmarks/persodub/fixtures/translation_synthetic_controls_v1.json \
  --real-report ~/Documents/PersoDub-Research/reports/p1-translation-qe-20261101/2026-10-31.json \
  --out ~/Documents/PersoDub-Research/reports/p1-translation-controls-20261101/controls-nli-and-real.json \
  --nli
```

COMET has its own environment `~/Documents/PersoDub-Research/venvs/persodub-cometqe-20261101` with `unbabel-comet==2.2.7`, `setuptools==80.9.0`; checkpoint `Unbabel/wmt20-comet-qe-da`, Hugging Face revision `2e7ffc84fb67d99cf92506611766463bb9230cfb`. Exact checkpoint SHA-256 is in the local COMET report. COMET `predict()` on a Mac CPU requires `num_workers=1` to avoid a library error involving `multiprocessing_context='fork'` with zero workers.

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-translation-controls-20261101
~/Documents/PersoDub-Research/venvs/persodub-cometqe-20261101/bin/python \
  -m benchmarks.persodub.translation_comet_probe \
  --controls benchmarks/persodub/fixtures/translation_synthetic_controls_v1.json \
  --previous ~/Documents/PersoDub-Research/reports/p1-translation-controls-20261101/controls-nli-and-real.json \
  --checkpoint ~/.cache/huggingface/hub/models--Unbabel--wmt20-comet-qe-da/snapshots/2e7ffc84fb67d99cf92506611766463bb9230cfb/checkpoints/model.ckpt \
  --out ~/Documents/PersoDub-Research/reports/p1-translation-controls-20261101/controls-comet-and-real.json
```

New test files cover synthetic paired preferences, score integrity, source-bound report identity, stale control rejection, cross-language fact hints and false positive numeric inflections. Current revision full test evidence: Python **2,613 passed, 5 skipped**, UI Node **1,143 passed**, desktop Node **713 passed**; Ruff, Python compileall, inline UI syntax and `git diff --check` **PASS** on the Mac. The controls remain synthetic, not a measure of production translation accuracy. No GitHub Actions, no mass datasets, no private transcripts, no weights in Git. All model scores are `OBSERVED`, not `PASS`.

## Next concrete action

Freeze **independently bilingual-reviewed annotations** for five natural-source low scoring intervals plus a *correct but lexically distant* paraphrase, with EN transcript verified separately from speech. Only then evaluate which metrics and facts can rank actual translation adequacy on unseen examples. Keep A4 as the sole authority over any future translate/preserve action and do not automatically rewrite a user subtitle based on these model scores.
