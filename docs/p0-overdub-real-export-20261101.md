# P0-A / P0-B: source-exact Overdub regression (2026-11-01)

**Implementation branch:** `feature/vocal-p0-overdub-acceptance-20261101`, based on handoff commit `325715eb04d6319325b8321b792e2901b32140dc` (which includes the PR #32 source tree). This document describes actual commands executed on Mac M1 Max, not an automated production acceptance.

**Scope of the measured real-media result:** an end-to-end re-export of the user's existing completed 234.7-second lesson with an A4 **all-REVIEW** event plan. No video source, Qwen TTS files or existing job state was modified; the experimental output was generated in an independent local QA folder using symlinks to source assets. Because all intervals were REVIEW, this test proves stream integrity and protected-source behavior only. It does **not** grade quality of a Russian dub or approve translating singing.

## Reproduced starting failure

Source: *Breath Control for TOTAL Beginners*, completed local job `a45f8233`.

- Source MP4 SHA-256: `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`.
- Original video stream: 234.633 s / 7,039 compressed packets.
- Original audio stream: 234.684082 s / 10,107 AAC packets, stereo 44.1 kHz.
- Existing `dubbed.mp4`: one AAC audio stream, declared `replace`; requested `overdub`.
- Existing diagnostics: SPK1 reference 0.90 s paired with 18 English words; five TTS line slot overruns totalling 3.14 s; one actual speech truncation 1.461 s. **These synthesis/diarization defects remain unresolved**; they are not masked by a correct export.

Reproduction command, run from the checked-out repository:

```sh
python -m app.dub_quality_audit --work-dir "/path/to/existing/job" --expected-mode overdub --output "/new/read-only/report.json"
```

The output status was `review_required`, with the exact issues above.

## Three concrete export defects fixed

1. **Protected interval contamination at fades.** The previous raised-cosine envelope extended half of a speech transition into adjacent PRESERVE/REVIEW source frames. Both protected classes were measurably remixed. All crossfades now remain **inside the TRANSLATE interval** and protected frames have exactly 1.0 original, 0.0 dub gain. New PCM test first failed for both PRESERVE and REVIEW, then passed byte-for-byte after the fix.
2. **Original track re-encoded despite the "Original" contract.** FFmpeg previously used `-c:a aac` and `apad` on both streams, destroying compressed packet identity. The mux and length-repair paths now encode/pad the Overdub track only and **stream-copy** the Original audio track. Real FFprobe packet hashes validate identity.
3. **Missing AAC tail when the video stream ends first.** Source video ended 51 ms before the source audio. FFmpeg `-t` used only video duration: the first real export retained 10,105/10,107 original packets, losing two. The mux now chooses the longer of video and source-audio stream durations; length repair also respects the retained Original audio duration. A new 2-second video / 2.4-second audio fixture first failed, then passed.

After mux and optional length correction, the export code uses FFprobe to **verify** that the resulting MP4 actually has a video stream and exactly two audio streams, named Overdub and Original, with the correct default disposition. Failure aborts before publishing a finished file; metadata alone is not trusted.

## End-to-end real source verification

Two technical runs were made from the same real source in an isolated test job:

| Measurement | Before duration correction | After duration correction |
| --- | ---: | ---: |
| Source AAC packets | 10,107 | 10,107 |
| Original AAC packets in exported MP4 | 10,105 | **10,107** |
| Source vs Original packet SHA-256 sequence | FAIL | **IDENTICAL** |
| Source vs exported video packet SHA-256 sequence | IDENTICAL | **IDENTICAL** |
| Output audio streams | 2 | **2** |
| Audio labels | Overdub, Original | Overdub, Original |
| Original audio codec/sample rate | AAC / 44.1 kHz | AAC / 44.1 kHz |
| Overdub audio codec/sample rate | AAC / 48 kHz | AAC / 48 kHz |
| Output container duration | 234.637642 s | **234.684083 s** |

The corrected output's exact original bitstream contains 10,107/10,107 packets. Video contains 7,039/7,039 identical compressed packets. Source SHA-256 matched the previously pinned S2ST source identity.

All re-exported audio was A4 REVIEW. The primary Overdub track therefore carries protected original content (encoded in the output container); **no speech was approved or translated**. The secondary Original track is the source compressed stream byte-identical at the packet level. This is technical PASS for the measured case, not perceptual acceptance.

## Test execution

Platform: macOS arm64 / Mac M1 Max, CPython 3.11.16, pytest 9.2.0, Ruff 0.16.6, Node 26.10.0, FFmpeg 9.0.2.

- Focused Overdub/PCM/real FFmpeg/API tests: **37 passed**.
- Full Python regression on this branch, including NumPy needed by fake SeamlessM4T tests: **2,576 passed, 5 skipped**.
- Full Node UI: **1,138 passed**; `ui/check-inline.mjs`: PASS.
- Desktop Node suite: **713 passed**.
- Ruff `check app benchmarks tests`, Python `compileall`, and `git diff --check`: PASS.
- No new model downloads, TTS inference, GitHub Actions or modifications to `main`.

The initial full Python attempt halted after 1,972 passes due solely to absent NumPy in a newly assembled test venv; installed NumPy 2.4.6 in that **isolated test venv**, then full regression passed. This is test environment configuration, not a product defect.

Local reproducibility records: `~/Documents/PersoDub-Research/reports/p0-overdub-20261101/` on Raymonds-Laptop.local, including baseline JSON, ffprobe packet validation JSON and test logs. Temporary REVIEW-only rendered MP4s/PCM were removed after validating and recording packet hashes; rerun the documented export for a new artifact. Source media and model weights are **not** committed to Git. The test source under `/private/tmp/vld-overdub-review-20261031/` is ephemeral; check existence/hash at the start of a new agent session.

## Remaining work and next action

**P0-A is complete for this snapshot**: repository/branch, exact real input, baseline failure and test harness have been verified.

**P0-B technical stream preservation is complete for the measured case**. The earlier one-track `dubbed.mp4` is still a replace-mode artifact; it has deliberately not been overwritten. The Overdub option is a separate reviewed re-export flow. The current all-REVIEW technical validation does **not** prove that translated speech is intelligible, unclipped, well paced, or has a natural Russian accent.

**Next action:** bring the read-only `app.dub_quality_audit` outcome into the finished-job UI with the *actual expected output mode*, then collect independent human-reviewed mixed speech/vocal exercise intervals on the 234.7 s source. Test a genuinely approved TRANSLATE/PRESERVE plan with natural Russian audio and no clipped words, preserving the exact original packets proven here. This is the P0-B to P1-A bridge. Keep A4 the sole source of translation permission.

**Known format boundary:** exact source stream-copy is measured for AAC in MP4. Non-MP4-compatible source audio codecs need separately tested container/remux behavior, not an unverified equivalence claim.
