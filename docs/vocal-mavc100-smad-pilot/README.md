# A2 SMAD benchmark: three source-frozen MAVC100 clips

**Status 2026-10-31:** actual model inference was performed on the owner's Mac; this branch records a small, independently replayable *numeric* diagnostic. It does not qualify lesson-level translation policy or author human gold annotations.

## Provenance

- Source labels: MAVC100 original **audio-stream** speech/singing event annotations, as used in A2 PR #18/#19. These are musical performances, not vocal instruction. `speech` does not mean `explanation`.
- The source video SHA-256 and annotation CSV SHA-256 per clip are recorded in [observations.json](observations.json). Original sources were three selected 30-second MP4s; none is committed here.
- SMAD: `duclvQ/smad`, revision `157a6316366bcf8831baf23df742edb71f07eb47`, checkpoint SHA-256 `63818291e401ca27616cb29ba3a224b780296ac4af87e6d6b70edb9daa40f5bc`, 834,020 parameters. Executed on Apple Silicon with PyTorch 2.6.0, Transformers 4.57.3, librosa 0.11.0.
- Actual selected inference used a four-second receptive audio window with one-second increments, projected onto **90 one-second labels** across 3 clips. The original published labels provide **35 event intervals**. These are coarse predictions, not 1-second-independent acoustic decisions or event-boundary ground truth.
- Events are projected from original label milliseconds to the source's **48,000 PCM samples per second**, including the explicit clipped silence-only end tail (30.030 -> 30.000 s per clip). Unannotated portions do not enter speech/singing recall denominators.

## Results

| Metric | SMAD | INA SMN, previously measured in PR #19 |
| --- | ---: | ---: |
| Gold speech | 21.035 s | 21.035 s |
| Gold singing | 49.266 s | 49.266 s |
| Singing incorrectly labeled speech | 0% | 0% |
| Speech labeled speech | **11.99%** (2.522 s) | **29.74%** (6.256 s) |
| Singing explicitly labeled singing | **65.93%** (32.481 s) | Not an INA class |
| Speech incorrectly labeled singing | **36.35%** (7.646 s) | Not an INA class |
| Singing events touched by predicted speech | **0 of 13** | **0 of 13** |

A policy requiring *both* INA and SMAD speech votes has a strict possible speech-coverage upper bound of **11.99% on these particular clips**, before A4 boundary review. This cannot be generalized to instructional voice lessons and does not establish that the two label ontologies are semantically equivalent.

SMAD supplies useful evidence of singing presence, but neither its `singing_music` nor `none` class proves the acoustic intent of a vocal technique; the broad four-second receptive field can smear transitions. Preserve A4 as the sole owner of translate/preserve/review decisions.

## Reproduction

From a checkout of this PR on Python 3.11+:

```sh
python -m app.vocal_smad_mavc_score --observations docs/vocal-mavc100-smad-pilot/observations.json
python -m pytest tests/test_vocal_smad_mavc_score.py -q
```

Pure Python standard library is sufficient to replay counts; only pytest is required for tests. This verifies deterministic arithmetic from **frozen numeric observations**, not fresh inference or validation of the absent original media bytes.

## Next gate

Independently adjudicate real EN/DE spoken-explanation/vocal-demonstration transitions using the A1 human schema from PR #16, then compare event-level protected-exercise recall and usable speech coverage to the A1 independent reference. Use at most one time-aware audio-language model on selected uncertain intervals; its labels remain unreviewed proposals until compared against A1 ground truth.

No media, model weights, song lyrics, raw transcripts, pipeline changes, WhisperNotes changes, GitHub Actions or auto-merge are introduced.
