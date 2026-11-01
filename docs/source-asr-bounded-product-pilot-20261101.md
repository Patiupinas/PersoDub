# PersoDub: bounded original-language STT pilot

**Date:** 2026-11-01. **Parent:** draft PR #40 `feature/vocal-a4-source-audio-review-20261101` at tree `d9a17a4b992271228395d8351a01e2f61e6efee6`. This is a separate opt-in change, not a change to default Whisper, TTS, live jobs, A4 or `main`.

## Why

The completed *Breath Control for TOTAL Beginners* local dub `a45f8233` had a damaged original-language Whisper transcript. It contained 106 collapsed word timestamps among 731 words; its Russian translation included semantic distortions. An earlier **research-only** Large-v3 re-decode in eight overlapping short source-audio windows produced 647 uniquely owned words, none collapsed. Independent Parakeet-v3 English ASR corroborated the critical 145-179s passage. The original source and the original translated video remained unchanged.

The research probe did not have a supported route into the app's source STT. This patch supplies that exact limited route, with an explicit setting and no additional model.

## Runtime behavior

- The existing `app/scripts/whisper_transcribe.py` gains `--bounded-source` for **one original media file**, requiring `--word-timestamps --language en|de|es`. Batch TTS-take scoring and the default one-shot source mode retain their previous behavior.
- `app/scripts/whisper_source_chunks.py` decodes **34s** original PCM windows, each overlapping its neighbor by **5s**. Inference uses the installed Faster-Whisper model with **beam 5**, source language fixed to the explicitly selected code, word timestamps, previous-text conditioning inside each bounded window and VAD disabled. Model is loaded once per run. Every window is read from original video/audio with FFmpeg, not a generated Russian dub.
- Midpoints of source word timestamps assign each overlapping word to **one disjoint source-time ownership core**. A4 later translates source seconds to its canonical 48k PCM frame clock; STT does not approve event boundaries. The translated/dubbed pipeline uses the resulting ordinary `start/end/text/words` cue format. A missing word alignment, collapsed timestamp, non-finite/out-of-range time, or empty result stops this experimental worker rather than inventing a valid transcript.
- The current isolated pilot supports sources up to **30 minutes** and only explicit source `en/de/es`. It does not implement real multi-hour checkpoint/resume. The 234.7s **English** case is the only real acoustically measured source in this change; DE/ES have no real test media or human accuracy labels yet.
- Normal app jobs are **unchanged**. To opt in, write `PERSODUB_SOURCE_ASR_MODE=bounded` in the desktop kit's `kit.env` or supply the setting through the existing server environment and explicitly choose EN, DE or ES as **source**, not target, language. Without a supported explicit source language, the pipeline logs why it keeps the old source decoder.
- Source `transcript.json` now records `source_asr_mode` and `source_asr_language` with the derived cues. Resume never silently reuses a legacy transcription after opting in, or bounded transcription after opting out/changing the source language. This forces the existing downstream translated-script and voice-work reuse gates to rebuild with the correct source clock. Legacy transcripts without that metadata continue to resume as legacy when bounded mode is off.

**A4 authority is unchanged:** source ASR is acoustic text, not permission to translate singing, trills or exercises. The completed-job Overdub reviewer still starts every event as `REVIEW`. No model text becomes a human-reviewed vocal-action plan.

## Real Mac result

Mac M1 Max, 64GB RAM; installed local Faster-Whisper Large-v3; original source MP4 SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`. Original model and input weights are not bundled or changed. The worker ran the entire original 234.684s source in **146.97s**. No network model download or GitHub Actions.

| Check | Old completed-job source transcript | Product bounded-source worker |
| --- | ---: | ---: |
| Cue count | 41 | 74 |
| Word timestamps | 731 | **647** |
| Zero-length words | **106** | **0** |
| Source-timing review cues | 12 | **3** (high-word-rate only) |
| Uniquely owned word lexical sequence versus prior independent benchmark | Not compared to word-level fresh ground truth | **1.00000** (647 of 647 in sequence) |
| Downstream `_pick_source_cues` script candidates | 32 | **27** |
| Maximum candidate line duration | 10.02s | **9.84s** |

The source spelling from real worker agrees exactly with the earlier independent *same-model* chunk benchmark, but neither is independent human transcript gold. The three remaining source QA cues reflect high speech rates, not collapsed word times. The reopened English passage describes breath management, relaxing the throat, an inward/upward abdominal movement and maintaining chest position instead of the previous implausible Russian content. **No Russian audio has been regenerated** by this task.

## Reproduce without changing a job

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-bounded-source-stt-20261101
JOB="$HOME/Documents/PersoDub-Research/demos/p0-quality-ui-20261101/workspace/2026-10-31/Breath Control for TOTAL Beginners_ru"
REPORT="$HOME/Documents/PersoDub-Research/reports/p1-bounded-source-stt-20261101"
WHISPER_MODEL_DIR="$HOME/.persodub-dev-kit/models/whisper/faster-whisper-large-v3" \
  "$HOME/.persodub-dev-kit/engines_venv/bin/python" \
  app/scripts/whisper_transcribe.py --audio "$JOB/input.mp4" \
  --language en --word-timestamps --bounded-source \
  --output "$REPORT/new-candidate.json"
```

**Private Mac outputs**, all outside Git: `real-bounded-source.json`, `candidate-original-bounded.srt`, `real-validation.json`, `real-run.log`. Existing `transcript.json`, `original.srt`, `translated.srt`, Qwen WAVs and output MP4 are unchanged.

## Verification and next step

Focused STT/worker/resume pipeline tests and actual FFmpeg PCM tests are in `tests/test_whisper_source_chunks.py`. On the exact Mac M1 Max branch snapshot: **2,684 Python passed, 5 skipped**; **1,146 UI Node passed**; **713 Desktop Node passed**. Ruff `app benchmarks tests`, Python compileall, English/Korean JSON validation, UI inline module check and `git diff --check`: **PASS**. The real same-source 234.684-second worker executed successfully with SHA-bound model/source evidence. No claims of native Russian accent, bilingual adequacy, human acoustic gold, or six-hour scalability are made from the source-only timing results.

**Next:** use the repaired source English to synthesize and audition a **separate 34-second Russian preview**, with source-correct translation, original bed and source-only A4 event review; compare this preview against the old dub's clipped lines and Russian-accent defects before turning the new STT mode on for all jobs.
