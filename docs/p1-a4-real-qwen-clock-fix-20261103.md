# P1-E: real-Qwen A4 trial exposed source/separator PCM-clock mismatch

**Date:** 2026-11-03
**Branch:** `feature/vocal-a4-silent-tail-20261103` stacked on Draft PR #46. Not merged to `main`.
**Machine:** local 64 GiB Mac, Qwen3-TTS model cached, Apple MPS, FFmpeg, existing original local lesson.

## Reproduced failure and cause

The first *real* execution of `run_dub(audio_mode="overdub", require_cached_source=True)` with four conservatively selected Russian dialogue cues successfully cloned, generated all four Qwen3-TTS WAVs and passed the voice-leakage gate. At the final A4 mixer it raised `OverdubError: Translated WAV must not outlast the source by over 50 ms` after **117.28 s** of work.

- Source-video clock from the production `media.video_duration` and `extract_original_pcm`: **234.633 s**, **11,262,384 PCM frames** at 48 kHz.
- Cached original Demucs `background.wav` and Qwen voice-only bed: **234.684083 s**, **11,264,836 frames**.
- Difference: **2,452 frames, 51.083 ms**, exceeding the previous **2,400-frame** threshold by just 52 frames.
- All **2,452 surplus PCM frames were byte-zero**. This is container/audio tail padding after the source-video clock, not translated speech and not a different source. The source-clock hash and reviewed event plan still matched.

## Small fix and regression

`app.audio.overdub.render_overdub` retains its existing up-to-50-ms non-silent tolerance. Above 50 ms it accepts only up to **250 ms** and only after scanning the **entire extra PCM tail**, in bounded chunks, for exact zero bytes. It then mixes only the original source's verified PCM frame count. It still rejects any longer overhang and any nonzero sample past 50 ms. No plan, source, default replacement path, output stream routing or sample clock was modified.

Tests added:

- Unit: the **exact 2,452-frame zero tail** reproduces the failure before the fix and passes after it, with source-clock-length output and protected samples intact.
- Negative: nonzero 2,452-frame tail and zero 12,001-frame overhang are rejected.
- End-to-end synthetic FFmpeg: the source-bound selective-TTS route builds an actual dual-audio MP4 using both exact and +2,452-silent-frame voice clocks. Legacy API and replacement-dub behavior remain covered.

## Executed real output (private media stays on Mac)

Folder: `~/Documents/PersoDub-Research/reports/p1-a4-real-inference-20261103/`

Source video SHA-256: `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`
Final output: `pilot-four-cues/dubbed.mp4`
Final MP4 SHA-256: `4bbab3c029e708fba28232a5691f7b82441690e2ca54eb769b0fef80f3dce38a`

- Original cached **separation, ASR and provided translation** reused in under one second.
- Real Qwen3-TTS **4/4 speech cues generated on Apple MPS**, 1 take each, **113.1 s** synthesis stage; no clipped lines. The model did **not** synthesize the remaining 28 cues.
- After the mixer fix, resume reused **all four existing WAVs in 0.3 s**, no new voice generation; full restart-to-MP4 result **17.75 s**.
- Source PCM: **11,262,384 frames**. TRANSLATE: **1,300,320 frames = 27.090 s**. REVIEW: **9,962,064 frames = 207.543 s**. All 9,962,064 protected frames were **bit-identical** to the decoded source. PRESERVE was **0 frames** in this provisional research test; *no human A4 approval was simulated*.
- Video SHA packet sequences matched input for **7,039/7,039 packets**; Original AAC packet SHA sequences matched input for **10,107/10,107 packets**. Output MP4 has selectable `Overdub` and `Original` audio streams, original total container duration **234.684082 s**, new **234.684083 s**.
- Independent **faster-whisper-large-v3, CPU int8** readback from the four real Qwen WAVs: **1 word error / 58 Russian reference words, WER 0.017241**. It measures lexical recoverability only, **not** native-Russian accent, emotional fidelity, speaker similarity or bilingual semantic accuracy.
- Model sidecar started only for the real research inference and was explicitly stopped after generation. Full original video, reference stems, target scripts, event plans, four Qwen clips and the result stay on Mac; no private audio, model weights or data samples committed to Git.

A further voice-reference observation: `speaker_refs.json` includes a **1.08 s** SPK1 reference paired with much longer transcript text, despite all four selected cues being SPK0. This is not accepted as clean speaker gold and is not a native voice-similarity PASS.

## Exact validation

- Python `pytest tests`: **2,775 passed, 5 skipped**.
- Web UI `node --test ui/src/*.test.mjs`: **1,150 passed**.
- Desktop `npm test`: **713 passed**.
- Ruff, Python compileall, inline assets and Git diff whitespace validation: PASS.
- The full four-minute **human-accepted** Russian dub was **not** completed: 28/32 cues intentionally remained in the original because the source has no human-certified singing/trill A4 plan.

**One next action:** listen to and correct the actual source A4 speech-versus-vocal-exercise partition, including model-flagged candidates 60-62, 66-68, 126-130 and 144-146 s and speech-leading singing/trill regions. Then run a real full-length selective-TTS comparison with native-Russian blind ratings. Do not relabel model proposals as human review.
