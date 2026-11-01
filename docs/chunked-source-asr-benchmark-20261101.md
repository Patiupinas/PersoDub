# PersoDub P1-B: bounded source-ASR comparison and checkpointed overlap audit

**Date:** 2026-11-01, Europe/Madrid.
**Baseline:** draft PR #38, `feature/vocal-source-asr-crosscheck-20261101`, GitHub head `b29a118231ade9f231de5d8f2ef33dfc53fe6f71`.
**This change:** research-only `benchmarks/persodub/chunked_source_probe.py` plus synthetic contract tests. No changes to production STT selection, translation, A4, source media, or dubbed jobs.

## Measured evidence on the real 234.684-second vocal lesson

The entire original video `input.mp4` of job `a45f8233` was independently re-decoded using the **installed** local Faster-Whisper Large-v3 checkpoint, not a different new model and not the dub audio. Input SHA-256: `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`; frozen original `transcript.json` SHA-256: `6043f3f9a540158001889b492a0feeb8f711c3ebce62e4bfc74de504c26e7a8b`. Exact installed `model.bin` SHA-256: `69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1`; config SHA-256: `a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9`. Faster-Whisper 1.2.1, CPU int8, beam 5, English fixed, word timestamps enabled, `condition_on_previous_text=True`, VAD filter off.

The new probe divides the original source audio into **8 bounded windows, each up to 34 seconds, with 5-second overlap**. The overlap is assigned to nonoverlapping ownership cores by the halfway point, avoiding double-counting word timestamps while retaining raw per-window evidence.

| Input start-end (s) | Original zero-duration words | Re-decoded owned zero-duration words | Worker wall time (s) |
| --- | ---: | ---: | ---: |
| 0-34 | 0 | 0 | 25.79 |
| 29-63 | 0 | 0 | 23.88 |
| 58-92 | 0 | 0 | 25.62 |
| 87-121 | 10 | 0 | 27.38 |
| 116-150 | 16 | 0 | 20.87 |
| 145-179 | 59 | 0 | 20.65 |
| 174-208 | 0 | 0 | 21.35 |
| 203-234.684 | 21 | 0 | 21.76 |

**Results:** 8/8 completed; 0 timeouts; 0 errors. Original frozen source transcript had **106 zero-length word timestamps out of 731**. New result contains **0 zero-length timestamps out of 647 owned words**. Across all raw windows, including intentional overlap, **0/759** word times collapsed; 112 overlap word occurrences were not owned by that particular window and therefore not counted twice. Individual worker elapsed times total **187.30 seconds**; this is a single small research run on an M1 Max, not a performance budget or benchmark for the full 2-6-hour pipeline.

### Adjacent overlap consistency

All **7/7** neighboring 5-second overlaps were independently decoded on both sides and compared as lexical consistency probes. After normalizing strictly ascending sung-letter sequences (e.g., `ABCD` versus `A, B, C, D`), none exceeded the diagnostic disagreement rule. Ordered lexical agreement ratios were **1.000, 0.842, 0.981, 1.000, 0.923, 0.750, 1.000**. The initial unnormalized probe falsely flagged the 58-63-second overlap because one decode returned a compact four-letter vocal exercise and the other separated those same four letters. A targeted synthetic regression test now preserves their equivalence without hiding a genuinely missing letter.

This is only **text-consistency evidence**. It is neither a human-certified overlap transcript nor proof that source singing/exercises were correctly detected or retained. Reviewable raw words and both overlapping decodes remain in the private JSON.

**Severe transcript-content difference:** original source in 145-179 seconds has very low ordered lexical overlap with the re-decoded source (0.05208). Fresh decoding gives coherent explanations about breath control, releasing throat tension and abdominal movement. The saved source contained unrelated repetitions and phrases. This indicates **the original source transcript is not a trustworthy ground truth for translation adequacy**, but neither machine decode has been certified by a human listener.

## Interpretation

- **PASS, technical:** the new bounded decode completed every selected window, respected original media hashes, resumed without repeating finished chunks, and emitted no zero-duration word timestamps in all 759 raw observations.
- **Not established:** exact cause of the old full-clip decoder failures, lexical completeness, accurate syllable/word recognition, voice similarity, Russian translation naturalness, correct distinction between instructional speech and vocal trills, or correct A4 preservation intervals.
- Original Whisper model weights SHA for the original job was **not recorded**. This new run uses the currently installed Large-v3 checkpoint; we cannot attribute all differences to chunking alone. Source time boundaries and model version also need control in any further causal comparison.
- Re-decoded speech around 171-181 seconds is still **not A4 gold**; a model may skip nonverbal trills, hallucinate a speech segment, or confuse speech with a demo. Human-reviewed source events remain separate.
- The lexically ordered source-word coverage metric is a **diagnostic, not WER, not semantic similarity and not a percentage of translated correctness**.

## Implementation contracts

`benchmarks/persodub/chunked_source_probe.py` reuses `source_asr_crosscheck.decode_audio_window` and `app.source_transcript_quality`. It:

1. Validates window size, duration, original media/transcript/model availability and explicit output location.
2. Fingerprints exact original media, transcript, model weights, model config and decoder settings; refuses to resume a mismatched checkpoint.
3. Uses a **fresh subprocess for each audio window** with a bounded wall-time timeout. Reports an explicit `timeout` or `error`, rather than silently treating missing words as accurate transcription.
4. Saves each complete result to an atomic local JSON checkpoint, never copying or overwriting the input media. Restart skips completed windows. Previously failed windows run again only with `--retry-failed`.
5. Optionally checks selected zero-based window indices (`--only-indices 4,5,7`) before continuing all others.
6. Assigns overlap to disjoint ownership cores using midpoint word timestamps, retaining raw window data so overlap/fragmentation can be audited. Compares the raw decoded wording in each adjacent overlap and flags one-sided or strongly different lexical output. An explicit ascending-letter normalization prevents the known ABCD vocal-exercise false alarm.
7. Exposes only `OBSERVED` diagnostic metrics and sets `asr_gold=false` and `translation_adequacy_verified=false`.

**Local, private output:** `~/Documents/PersoDub-Research/reports/p1-asr-chunks-20261101/chunked-large-v3-default.json` (~128 KB); it includes full source words, so it is excluded from Git.

### Reproduction (Mac, existing local weights)

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-asr-chunks-20261101
JOB="$HOME/Documents/PersoDub-Research/demos/p0-quality-ui-20261101/workspace/2026-10-31/Breath Control for TOTAL Beginners_ru"
PYTHONDONTWRITEBYTECODE=1 "$HOME/.persodub-dev-kit/engines_venv/bin/python" \
  -m benchmarks.persodub.chunked_source_probe \
  --source-media "$JOB/input.mp4" \
  --original-transcript "$JOB/transcript.json" \
  --model-dir "$HOME/.persodub-dev-kit/models/whisper/faster-whisper-large-v3" \
  --report "$HOME/Documents/PersoDub-Research/reports/p1-asr-chunks-20261101/chunked-large-v3-default.json" \
  --timeout-seconds 70
```

On the already completed report, the command verifies source+model identity and resumes with **zero new decodes**.

## Verified regression evidence on M1 Max

- **Python full:** 2,663 passed, 5 skipped (`tests/`, 78.68 seconds).
- **UI Node tests:** 1,144 passed.
- **Desktop Node tests:** 713 passed.
- **Source chunk benchmark:** 8/8 real CPU worker windows completed, 0 timeouts, 0 errors; saved identity matches the original source/video, frozen transcript and installed model.
- **Boundaries:** 7/7 adjacent overlaps analyzed; 0 lexical disagreement flags after evidence-grounded ascending-alphabet normalization, with no acoustic accuracy claim.
- **Code validation:** Ruff `app benchmarks tests`, Python compileall, locale JSON parsing, inline UI check and `git diff --check` PASS. No GitHub Actions run.
- **Privacy:** source transcriptions and benchmark reports saved locally under `reports/p1-asr-chunks-20261101/`, outside Git.

## Next decision point

To move from research to reliable product behavior, independently review **the 145-179-second original audio** against the new English transcription and explicitly validate speech/vocal-event boundaries with A4 before enabling a new source-ASR setting in the app. Only then evaluate automatic translation-quality scores on a corrected source transcript. Product `main` and live running jobs are unchanged.
