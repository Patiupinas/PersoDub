# MAVC100 real acoustic comparison - three selected videos, 2026-10-30

This is an **executed** INA speech/music/noise acoustic baseline and source-PCM-weighted **MAVC100 performance-video label comparison**, not human gold for a vocal teaching lesson. Nothing here grants `TRANSLATE` permission. Original MAVC100 audio/video is research-use-only and **no videos or waveforms are included in this repository**.

## Source and selective-download provenance

Selection and original video, label, and raw decoded PCM hashes are recorded in [vocal-mavc100.md](vocal-mavc100.md), [Draft PR #18](https://github.com/Patiupinas/PersoDub/pull/18). There are **exactly three 30-second H264/AAC video clips from three different original performances**, not the full 8-part RAR archive. An isolated Mac scratch directory contains the files; RAR member CRC32, original MP4 SHA256, original CSV SHA256 and decoded 48 kHz PCM SHA256 were verified.

The published source video container is 30.030 s, while its actual decoded first audio stream is 30.000 s. A trailing annotated silence interval ends at 30.030 s. The scorer clips **only this 30-ms silence tail (1,440 sample frames per file)**, rejecting any speech/singing label beyond the real audio PCM length.

## Model execution evidence

- **Host:** connected Apple Silicon macOS 27, 64 GiB RAM; Python **3.11.16**; FFmpeg 9.0.2
- **Isolated package:** inaSpeechSegmenter **0.8.0**, `Segmenter(vad_engine="smn", detect_gender=False, batch_size=16)`; TensorFlow **2.20.0**, official ONNX Runtime **1.31.1**, NumPy **1.26.4**, Keras **3.15.1**
- **Weights:** official `keras_speech_music_noise_cnn.hdf5`, exactly **3,244,808 bytes**, SHA-256 `f04b5e3c86fa2e81666d106b0867350fe7858c7bd006c2a74c27b5b45507e7d8`
- **Acquisition:** the initial SMN acoustic model file and, for a subsequent narrow A/B comparison, one additional **SM** weights file were downloaded; no other detector weights or new video datasets. The default INA PyPI GPU dependency was not installed on macOS; CPU-compatible dependencies were provided in a private, isolated `uv` environment as documented in the [Mac A2 audit](https://github.com/Patiupinas/misc/blob/design/vocal-dubbing-agent-architecture-20261030/vocal-lecture-dubbing/A2_MAC_DEPENDENCY_AUDIT_20261030.md).
- **Execution:** real, original, full-length 30-second MP4 input passed to the model; measured inference durations after model import **0.859 s**, **0.769 s**, **0.637 s**. Model output is a sequence of `speech/music/noise/noEnergy` timestamp spans; no ASR, TTS, or new diarization ran.

## Exact validated results

The scorer weights all sample counts by the decoded 48 kHz source PCM clock, using integer millisecond label intervals and rounded model timestamps, not a mean of per-clip percentages. It preserves model `noEnergy`, `noise`, `music`, `unclassified` categories instead of marking them as safe speech.

| Quantity, 3 clips | Real count / outcome |
| --- | ---: |
| Gold singing | **2,364,768 frames / 49.266 s** |
| Gold speech | **1,009,680 frames / 21.035 s** |
| Gold singing wrongly predicted speech | **0 frames / 0%** |
| Singing events touched by predicted speech | **0 / 13** |
| Gold singing predicted music | **2,076,288 frames / 87.8009%** |
| Gold speech correctly predicted speech | **300,288 frames / 29.7409%** |
| Gold speech predicted music | **708,576 frames / 70.1783%** |
| Published silence-tail frames excluded beyond actual PCM | **4,320 frames total = 3 × 1,440** |

| Clip | Sung frames | Sung frames predicted speech | Gold speech frames | Gold speech recognized as speech |
| --- | ---: | ---: | ---: | ---: |
| Ellie Goulding - Burn 3 | 149,424 | 0 | 549,120 | 300,288 |
| Jessie J - Bang Bang 5 | 926,832 | 0 | 363,168 | 0 |
| Jess Glynne - 123 4 | 1,288,512 | 0 | 97,392 | 0 |

These are **measured on three selected musical performances**; they are *not* an estimate of false-speech risk across all vocal techniques or a representative speech recall. The detector preserves singing in this very small sample (no sung frames labeled speech), but **fails to recover most onstage speech over music**, so it cannot be the only permission gate for replacing explanations.

## Same-source A/B test: alternate INA speech/music model

Ran `Segmenter(vad_engine="sm", detect_gender=False, batch_size=16)` on **the same three verified MP4 files** with no additional video/annotation downloads. Unlike SMN, the SM classifier has only speech and music classes for energetic regions. Its official weights file `keras_speech_music_cnn.hdf5` is **5,885,888 bytes**, SHA-256 `14379ba71352d8981bc24a15c069c84cf6f78ff2ffe7377d43b32465ebd06e01`. Both A/B runs use the same INA 0.8.0 install, decoding, PCM profile, label inventory and scorer.

| Metric across three clips | SMN (speech/music/noise) | SM (speech/music) |
| --- | ---: | ---: |
| Singing incorrectly predicted speech | **0 / 2,364,768 frames (0%)** | **52,416 / 2,364,768 frames (2.21654%)** |
| Singing events with any predicted speech | **0 / 13** | **1 / 13** |
| Gold speech identified as speech | 300,288 / 1,009,680 (29.74091%) | 313,104 / 1,009,680 (31.01022%) |
| Gold speech predicted music | 708,576 frames (70.17827%) | 695,760 frames (68.90896%) |
| Gold singing predicted music | 2,076,288 frames (87.80092%) | 2,238,768 frames (94.67178%) |
| Actual inference duration Ellie / Jessie / Jess | 0.859 / 0.769 / 0.637 s | 1.203 / 0.933 / 1.052 s |

**Interpretation:** In this selected sample SM recovered only **12,816 extra frames / 0.267 seconds of speech** but falsely classified **52,416 frames / 1.092 seconds of singing as speech** (the Jessie J clip). The conservative SMN mode is the better **first tested INA baseline** for *protecting singing*, but low speech recall requires an additional independent speech analysis. SM and SMN are **not two independent detectors** for A4 voting because they share a model family and frontend. None of these observations approves any vocal-lecture span for TTS.

## Reproducible pure-data scorer

The six **model-only prediction and score JSON files**, source-label audit and decoded-PCM metadata are committed in the [metadata-only pilot bundle](vocal-mavc100-pilot/README.md). They intentionally exclude source media, neural weights and the dataset's original CSV label contents. `tests/test_vocal_mavc100_pilot_snapshot.py` verifies the two model outcomes, source-video hashes, source-label hashes and aggregated frame denominators without network access. Original audio label CSVs can be fetched from the upstream 52,122-byte archive if independent re-scoring is desired.


`app/vocal_mavc100_score.py` uses only the standard Python library and the parser from PR #18, without loading any model or media. An independent inference agent supplies existing JSON with actual `speech/music/noise/noEnergy` intervals; the Mac pilot used the actual `inaSpeechSegmenter` output. It checks exact video and label SHA256 cross-document identity, source zero-time audio PTS, finite/nonoverlapping predicted intervals, no created silence outside PCM, valid counts, and prevents accidental overwrite.

```bash
python -m app.vocal_mavc100_score \
  --labels /path/to/Frame_level_labels_in_audio_streams \
  --audit /path/to/selected-only-gold-audit.json \
  --pcm /path/to/selected-3-pcm-audit.json \
  --predictions /path/to/ina_smn_predictions.json \
  --output /path/to/new-scores.json
```

**Output:** source-constrained per-clip confusion matrices, event contamination count, sample-weighted confusion, and model identifier/weight hash. This is a diagnostic file, not the canonical A1 manual label schema and not a generated media artifact.

The focused synthetic test suite covers event contamination, exact integer 48kHz sample weights, float representation artifacts, unknown prediction categories and gaps, source overlap, zero denominators, aggregator weighting and corrupt clock. On connected Mac, PR #18 + #19  **58 focused tests PASS** against real parser and model-agnostic scorer, pinned Ruff 0.16.6 **PASS**; the script successfully scored all three stored real inference outputs. Full repository CI and Mac tests are recorded against exact PR head separately.

## Next evaluation

1. Keep this **P2b music-performance diagnostic** as the baseline. It is excellent for detecting the risk of treating singing as explanation, but insufficient to prove broad explanation coverage.
2. On the **same three media files**, evaluate one independently sourced complementary speech detector under equivalent PCM/hash timing. Do not download entire corpora; preserve a source-disjoint holdout and measure whether additional speech votes improve recovery without starting to dub protected singing.
3. Separately evaluate **genuinely instructional EN/DE vocal-technique footage**, including sustained vowel, breath, trills, fry, growl, belt/scream and partial spoken instruction overlapping a demonstration. The previously found [natural lecture candidates](https://github.com/Patiupinas/misc/blob/design/vocal-dubbing-agent-architecture-20261030/vocal-lecture-dubbing/NATURAL_TRANSITION_SOURCES_20261030.md) are not yet human annotated and cannot be counted as PASS.

## Final local test evidence for the metadata-only scorer revision

The 6 small source/PCM/model JSON files in `docs/vocal-mavc100-pilot/` are *actual outputs* of the same Mac three-clip experiment, with temporary local filesystem paths omitted from the published PCM metadata. These files contain no audio, video, model checkpoints or raw dataset annotation rows. Tests `test_vocal_mavc100_pilot_snapshot.py` cross-check source hashes, selected clip IDs, PCM frame counts and re-aggregated sample metrics. The scorer CLI additionally rejects stale source SHA, label SHA, nonzero audio PTS, duplicate inventory, changed clip ID and overwriting an existing result.

**Connected Apple Silicon Mac, Python 3.11.16, code head `6091916144e3c9afd04304b43c5246e011036003`:** full repository `python -m pytest tests/ -q` => **2,506 passed, 5 skipped**, 67.13s; pinned `ruff==0.16.6 ruff check app tests` => **PASS**, `compileall` PASS and `git diff --check` PASS. The final documentation-only commit records these exact results; independently triggered cross-platform GitHub Actions must be reported separately and matched to its own exact head.
