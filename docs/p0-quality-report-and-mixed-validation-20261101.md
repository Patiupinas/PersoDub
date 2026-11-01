# PersoDub P0-B: Finished-media quality UI and mixed Overdub experiment

**Date:** 2026-11-01 (Europe/Madrid). **Implementation base:** PR #34 tree `912c46c0d4a3152c0af989445df4e4ed3891595d`. **Branch:** `feature/vocal-p0-quality-ui-20261101`. This follows `docs/p0-overdub-real-export-20261101.md`.

## Added product behavior

- A compact **Quality check** disclosure on the completed local dubbing's Script pane. It reads the actual finished video and keeps the summary visible during ordinary playback. A manual **Recheck** button refreshes; the app does not rescan short WAVs on every poll.
- `GET /api/dub/jobs/{jid}/quality` reuses the read-only `app.dub_quality_audit.audit_completed` function and audits the original finished `dubbed.mp4` under the actual job's declared output mode (default Replace). It cannot mutate media or original job state.
- `GET /api/dub/jobs/{jid}/quality?file=finished-overdub[-N].mp4` checks one exact separately saved reviewed Overdub output in the same job directory, not the original Replace file. The file name is allowlisted and resolved under the job root.
- The Overdub dialog notifies the quality view after a **successful** export. The report checks actual FFprobe video/audio streams, two audio stream names and default dispositions; it does **not** claim speaker likeness, Russian accent or other perceptual verification.
- The report clears on an unfinished/cloud/other-kind job, ignores late fetches from prior jobs, and refreshes after one-line/batch voice regeneration. It never alters the source or launches a voice model.
- English and Korean localization tables were updated consistently. The UI is intentionally small and uses the existing script-pane layout, not a new dashboard.

## Reproduced evidence on actual completed lesson

Source `a45f8233`, *Breath Control for TOTAL Beginners*, MP4 SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`.

**Actual Replace output**, when opened under the new interface: `review_required`; four issue codes:

1. `speaker_reference_too_short`: SPK1 reference 0.90 s.
2. `speaker_reference_text_mismatch`: SPK1 reference transcript does not match the short sample.
3. `timing_slot_overruns`: 5 lines overrun the source slots by a combined 3.14 s.
4. `speech_audio_clipped`: one line was cut by 1.461 s.

Puppeteer against Chrome on Mac opened the real job via Home, verified the visible summary **4 issues detected**, all four details, and a functioning Recheck. An actual screenshot exists locally as `reports/p0-quality-ui-20261101/qa-open.png`. The report is **not** an ABX/listening quality score.

**Separate technical mixed experiment:** the cloned job contains `finished-overdub-2.mp4`, built from the existing Qwen WAVs with `TRANSLATE` only for source 0.35-8.90 s, `REVIEW` for everything else. This was **not human-verified speech/singing ground truth** and must **not** be presented as a finished vocal lesson. It proves the mixer adds translation on selected audio and preserves the rest. The report is saved locally as `mixed-technical-validation.json`.

- Actual source AAC packets: **10,107/10,107 identical SHA sequences** on `Original`; video compressed packets **7,039/7,039 identical**.
- On decoded 48-kHz mono samples, source-vs-Overdub RMS difference during selected translation (3-5s) was **0.026178**, versus **0.000344** during protected original (40-42s). Lossy AAC on the mixed output precludes PCM byte identity in the packaged MP4; the underlying mixer preserves protected PCM at source precision (prior PR #34 tests).
- A real MP4 exposed a missing `stream_disposition=default` projection in the new audit's FFprobe query. The report initially raised a false `overdub_stream_metadata_mismatch`. Corrected the query, added a **real FFmpeg/FFprobe regression fixture** and reran the API: the mixed output now correctly reports two Overdub/Original tracks, with the same four synthesis-source issues, **without** a false stream-label failure.
- Tested in a separately cloned COW APFS workspace; did not mutate the original `a45f8233` job or user's ongoing `34d7c248` redub. Technical experiments do not call TTS.

## Test & machine receipts

- macOS arm64, Mac M1 Max, Python 3.11.16, Ruff 0.16.6, Node 26.10.0, FFmpeg 9.0.2.
- Initial focused backend QA tests **18 passed**, including actual FFprobe disposition output after the fix.
- Full Python regression **2,585 passed / 5 skipped**, Node UI **1,143 passed**, desktop **713 passed**; Ruff, Python compileall, UI inline-module syntax and `git diff --check` PASS on the Mac. See saved raw logs under `~/Documents/PersoDub-Research/reports/p0-quality-ui-20261101/`. These measurements are specific to this exact source tree, not transferable to later builds.
- Local demo service: `http://127.0.0.1:8871`, a sandbox demo job cloned using APFS copy-on-write. Its output file is available through `GET /api/dub/jobs/a45f8233/overdub/files/finished-overdub-2.mp4`. Confirm service/paths are still live in later sessions.
- The user-started redub `34d7c248` on the separate old server `8860` was in `running` state during this work. Candidate TTS for 32 lines finished at 17:42, and a separate **CPU-active 128-take Whisper ASR scoring child** remained busy at 17:51. No mutation or termination was made to that process. This ASR scorer has a separate dynamic timeout and can be expensive; do not call it stalled based on stale job log text.

## Remaining next actions

**Next:** obtain independent human-reviewed intervals for singing/exercise vs speech, and create a *genuinely user-approved* full reviewed A4 plan on the same lesson. Then compare QA and listening scores between the existing Qwen source and user-started redub, and focus on the 0.9-s SPK1 reference, native Russian accent and clipped/overlong phrases.

The current technical preview and automated QA **do not** solve speaker identity, timing or naturalness. An explicit full-video **Remake voices** UI action is still a separate UX improvement: the backend already has `POST /api/dub/jobs/{jid}/redub`, but the script-header Remake button currently targets changed lines only.
