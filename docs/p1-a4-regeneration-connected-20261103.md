# P1-D: approved A4 source -> fresh selective Overdub job

**Date:** 2026-11-03. **Feature branch:** `feature/vocal-a4-regenerate-20261103` stacked on Draft PR #45, no merge to `main`.

## Product behavior

The existing completed-local-job **Overdub** review dialog has two distinct ways to complete the same source-bound, explicitly reviewed A4 decision partition:

- **Mix saved voices** (previous behavior): reuses `qwen_line_*.wav` from the finished project and remixes two audio streams. This does **not** save inference time, does not re-speak edited text and can only export lines that were already made.
- **Rebuild reviewed speech** (new): starts a **new** JobStore dubbing job using the same manually confirmed A4 actions, preserving the old job and its original output. The new job's Qwen receives only complete Russian cues inside `TRANSLATE`; `PRESERVE` and `REVIEW` retain the original source untouched. The running job appears in Projects with the normal progress, cancellation and resume behavior.

The A4 review dialog still begins with every action `REVIEW`. AST suggestions are *not* approvals. If no cue qualifies for translation, the job needs no Qwen sidecar; an original-only two-track video can be generated. Approval and audio gains are saved as `overdub_events.json` and `overdub_levels.json` in the fresh job. Source audio is checked against the exact 48 kHz sample-clock SHA before allocating a job.

## Reuse, ownership and identity

Use the existing JobStore launcher and `app.dub_launch.work_for`, not a new runner. The fresh job copies only `input.mp4`, `source.srt` from `original.srt`, `sub.srt` from current `edited.srt` (or `translated.srt`), validated `separated.json`, `transcript.json`, and the two source separation stems. **No old `qwen_line_N.wav` is copied.** On the first run and after a restart, `resume=True` reuses the frozen separation and transcript caches; `require_cached_source=True` rejects missing caches rather than silently making a new ASR or running expensive separation. The configured ASR mode can change after the source job; it does not invalidate a purposely frozen source transcript.

JobStore persists the two small additional job fields: `audio_mode="overdub"` and `overdub_source_job=<original job ID>`. The existing original project remains unchanged. The A4 checksum, source, selected subtitle text, voice mode and take count continue to own TTS reuse identity. Runtime gain changes are applied in `render_overdub` with its already validated `OverdubLevels` profile, and the actual resulting media has the two selectable audio tracks `Overdub` and `Original`.

## Verified behavior

Tests cover end-to-end FastAPI initiation, exact source hash and reviewed-plan validation, missing stage-cache rejection, fresh-folder isolation, editing the full target SRT, Qwen-free all-REVIEW generation, persistent JobStore metadata on restore, `dub_launch.work_for` resume mapping, and new UI callback to display the running project.

A **real 3-second synthetic FFmpeg integration test** executes the new `run_dub` A4 path with cached stage inputs and a **stub TTS audio signal**. It asserts no real separation/ASR, a single eligible Russian cue, protected original PCM exactly copied after the A4 fade, full translation preserved, successful MP4 with **two named selectable audio streams**. This is **not** a real Qwen or native-Russian voice-quality evaluation.

## Project quality status / next action

The actual 234.684-second lesson's old plan contains zero `PRESERVE` actions, and all original 32 Russian cues lie inside `TRANSLATE`. That plan remains unvalidated for exercises, so actual selective TTS speed savings and a human-accepted Russian accent/voice/translation cannot be claimed yet. See `docs/p1-a4-pretts-gate-20261103.md` for 5 unapproved AST review candidates.

**Next action:** listen to the original lesson in the existing A4 dialog, accurately mark the vocal demonstrations as `PRESERVE` and spoken explanations as `TRANSLATE`, then use **Rebuild reviewed speech** for a genuine four-minute Qwen run and native-Russian blind listening evaluation. No new model is required for this step.
