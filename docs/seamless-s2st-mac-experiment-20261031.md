# PersoDub: Local audio-to-audio experiment, 2026-10-31

## Purpose

An opt-in research path for audio-in -> Russian-audio-out dubbing on Mac M1 Max.
This experiment does NOT replace the current Qwen pipeline or modify an
existing completed project. The user requires original audio retained, singing
and vocal exercises preserved, Russian without foreign accent, voice similarity,
and source pauses retained. These remain separate acceptance criteria.

## Model identity and reproducibility

- facebook/seamless-m4t-v2-large revision
  5f8cc790b19fc3f67a61c105133b20b34e3dcb76.
- Two official safetensor shards total 9,237,277,708 bytes. The optional
  Fairseq 11 GB checkpoint is unnecessary for Transformers and was discarded.
- Model weights are CC BY-NC 4.0; NOT redistributed with the app.
- Isolated Python 3.11, torch 2.8.0, Transformers 4.57.3, MPS acceleration,
  real Mac M1 Max with 64 GB unified memory.
- Actual architecture DOES use internal text tokens. No separate ASR,
  externally translated text or TTS provider is invoked by the S2ST module.
- The model does not clone a speaker's voiceprint by itself.

The source-code research for optional timbre transfer is Seed-VC at upstream
commit 51383efd921027683c89e5348211d93ff12ac2a8 (GPL-3.0).
Keep third-party source and its weights independent until independently tested.

## Implemented boundaries

- app/experimental/seamless_s2st.py:
  Check pinned local model shards, decode <=30-second source speech using
  FFmpeg to 16-kHz mono, one local MPS inference, output PCM16 WAV and
  SHA-256/elapsed-time/realtime-factor receipt. No source overwrite.
- app/experimental/seamless_batch.py:
  Select explicit source cue indices, check video and segment SHA, run many
  source clips through one reusable model, keep per-clip receipts and
  restartable progress under an exclusive directory lock.
- app/experimental/s2st_quality.py:
  Objective per-line duration/short-source triage, NEVER certify Russian
  accent, semantic correctness, voice identity or singing.
- app/experimental/s2st_preview.py:
  Use the existing PersoDub Overdub renderer, preserve a source audio track
  independently selectable from the translated mix, and never truncate RU
  speech to force it into a source speech slot.
- Existing benchmarks/persodub/blind_review.py:
  Generate shuffled Qwen-vs-S2ST A/B listening audio with its provider key
  stored separately outside the served reviewer directory.

## Real measured experiment

Cold inference: source English 6.90 seconds -> Russian WAV 7.46 seconds,
31.213 seconds MPS inference including model load, RTF 4.524.

One warm-session six-clip benchmark, no repeated model loads:

| Source index | Original (s) | Russian (s) | Inference (s) | RTF |
| --- | ---: | ---: | ---: | ---: |
| 4 | 4.02 | 3.46 | 5.237 | 1.303 |
| 5 | 8.14 | 6.70 | 4.128 | 0.507 |
| 6 | 6.38 | 5.08 | 3.503 | 0.549 |
| 9 | 6.90 | 7.46 | 4.702 | 0.682 |
| 11 | 6.04 | 6.42 | 2.950 | 0.488 |
| 19 | 1.08 | 33.06 | 19.183 | 17.762 |

All six result files and individual source SHA receipts exist.

Critical defect: the 1.08-second SPK1 cue generated 33.06 seconds of
Russian audio with a hallucinated subtitle credit, confirmed by an
independent CPU Whisper readback. Never automatically substitute or
truncate such audio. Quality triage found 3 of 6 needing review:
indices 9 and 11 overrun their source slots; 19 fails short-source,
extreme duration expansion and slot overrun. Indices 4, 5, 6 are
TIMING_CANDIDATE_ONLY, NOT validated translations.

Three genuine short video previews (4, 5, 6) were exported with
independently selectable Overdub and Original audio streams. Local URLs:
http://127.0.0.1:8861/previews/ and http://127.0.0.1:8861/
for the six-pair blinded reviewer lab. HTTP checks of MP4 and WAV
passed, while the reviewer private assignment key returned 404.

## Reproduction commands from the PersoDub experimental worktree

First verify that the pinned model weights are installed in the local kit.

python -m app.experimental.seamless_s2st --source /path/en.wav --out /new/ru.wav --model-dir /path/model --device mps --report /new/receipt.json

python -m app.experimental.seamless_batch prepare --job-dir /path/completed/job --indices 4,5,6 --experiment-dir /new/experiment

python -m app.experimental.seamless_batch run --experiment-dir /new/experiment --model-dir /path/model --device mps

python -m app.experimental.s2st_quality --experiment-dir /new/experiment --output /new/triage.json

python -m app.experimental.s2st_preview --source-video /path/job/input.mp4 --translated-wav /new/experiment/ru-004.wav --start 36.18 --end 40.20 --out /new/preview.mp4

All output paths are new research destinations. Original media remain unchanged.

## Outstanding scientific gates

- Label protected vocal exercises independently, before TTS or S2ST.
- Establish human-ground-truth Russian translation and independent
  phonetic assessments, not only WER on a second ASR model.
- Blindly compare source speaker timbre, Russian accent, pause placement,
  original soundtrack audibility and vocal-event preservation.
- Verify possible Seed-VC voice transfer; the code and weights are
  separate research candidates and do not establish an improvement yet.
- Full 2h/4h/6h run with memory/disk/clock and restartability benchmarking.
- A quality pass is not implied by finished inference, correct WAV format,
  or source-cue duration. Do not merge experiments into main by default.

No model binaries, private media, reviewer key, or personal audio appear in Git.

## Seed-VC v2 speaker-transfer probe on the same source

Seed-VC source version: commit
51383efd921027683c89e5348211d93ff12ac2a8, GPL-3.0.
Selected checkpoint revisions and paths were recorded only in the
Mac-local research manifest at
~/.persodub-dev-kit/research/seed-vc/research-model-manifest.json.
Ten selected weight/config files total 2,607,722,671 bytes.
No alternative model code or weights are bundled with PersoDub.

One real conversion succeeded with Apple MPS using 16 diffusion steps,
the original English 6.9-second SPK0 reference as the target timbre
and the 7.46-second Seamless Russian speech as source voice. A new
22.05-kHz PCM WAV was produced, duration 7.453605 seconds; the
model reported 27.83 seconds for its first complete voice conversion.

Uncalibrated CAMPPlus speaker embeddings (same source speech content)
against the exact English reference yielded:

| Russian candidate | Cosine embedding similarity |
| --- | ---: |
| Seamless Russian without voice conversion | 0.029422 |
| Seamless Russian converted through Seed-VC | 0.460944 |
| Existing Qwen RU take from the same source span | 0.599713 |

This is a single-speaker, single-utterance diagnostic. The numerical
embedding similarity improved after Seed-VC, but Qwen remained ahead.
These values are neither percentages nor blinded perceptual MOS.
A later comparison must validate the transcript stayed in Russian,
preserve original consonants and pause placement, and independently
rate accent, timbre and naturalness on additional speakers.

Seed-VC requires separate model/weight management. Do not promote
the GPLv3 research source or its checkpoint dependencies as automatic
product defaults based on this one result.

Independent RU Whisper Large-v3 on the converted WAV produced the
same normalized Russian words as before conversion (WER 0.0, CER 0.0
between these two model transcripts). This checks gross content
stability only. It does not establish correctness of the English-to-
Russian translation, accent quality, or the absence of phoneme errors
in either sample.
