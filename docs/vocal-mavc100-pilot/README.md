# MAVC100 selective acoustic baseline - metadata-only provenance bundle

**Created 2026-10-30, Draft PR #19.** This directory preserves *only* JSON metadata and original INA prediction/score outputs from the connected Apple Silicon Mac. It contains **no audio, video, model weights or original published CSV files**, and needs no download at CI time.

Exact experiment and model A/B: [../vocal-mavc100-scorer.md](../vocal-mavc100-scorer.md). Source video, original label and decoded PCM hashes: [../vocal-mavc100.md](../vocal-mavc100.md). Original research-use-only performance footage remains in [MAVC100](https://github.com/Yuanbo2020/Audio-Visual-VAD/tree/main/Open_dataset_MAVC100).

| File | Ownership and contents |
| --- | --- |
| `source-label-audit.json` | Pure parser v1 output for 200 published audio CSV labels, containing **three explicitly selected source-disjoint clips**, label file SHA-256 and the one malformed excluded label |
| `pcm-provenance.json` | FFprobe first-audio-stream clock and SHA-256 of **the decoded 48 kHz stereo PCM16** from each of the three selected real source MP4s, with temporary local paths removed before publishing |
| `ina-smn-predictions.json` | **Actually executed** INA 0.8.0 `smn` acoustic segments, exact source-MP4 SHA and official model weights SHA-256 |
| `ina-sm-predictions.json` | **Actually executed** INA 0.8.0 `sm` segments on the exact same source MP4s, alternate official model weights SHA-256 |
| `ina-smn-scores.json` | Frame-weighted scorer output from the original published label files and SMN predictions |
| `ina-sm-scores.json` | Same original labels and PCM profile, scored against alternate SM model outputs |

If the open original audio annotation archive is downloaded **separately for research**, with its 52,122 bytes and SHA-256 `325eecf30f3cb1c457c3c027a91e928b58ba286a15944f34210900131f0c9a49` verified, the stored predictions can be re-scored **without the original video or the neural model**:

```bash
python -m app.vocal_mavc100_score \
  --labels /path/to/Frame_level_labels_in_audio_streams \
  --audit docs/vocal-mavc100-pilot/source-label-audit.json \
  --pcm docs/vocal-mavc100-pilot/pcm-provenance.json \
  --predictions docs/vocal-mavc100-pilot/ina-smn-predictions.json \
  --output /tmp/recomputed-smn-scores.json
```

Use `ina-sm-predictions.json` to reproduce the alternate SM variant, and compare the aggregated counts to the corresponding frozen scores. The **actual inference** still requires source media and a compatible INA environment. Even perfect reproduction of these published performance-label scores does **not** constitute independently checked vocal-lecture gold.

**Frozen 3-file results:** INA SMN: **0 / 13 singing events touched** and **29.74% speech coverage**; INA SM: **1 / 13 singing events touched (1.092 seconds)** and **31.01% speech coverage**. Neither configuration grants translation permission; the models share a family and cannot count as two independent A4 votes.

All counts refer only to **three selected real 30-second videos**. No broad dataset or weights checkpoint was committed. Avoid interpreting `singing_predicted_speech_rate=0` as a statistical guarantee for other voices or unpitched vocal exercises.
