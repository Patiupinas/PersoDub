# P1: A4 decisions gate synthesis, source review remains human

**Date:** 2026-11-03. **Branch:** `feature/vocal-a4-pretts-gate-20261103`, stacked on Draft PR #44. This is an opt-in production Overdub improvement; normal replacement remains unchanged. The original project, unreviewed A4 plan, model weights, private media and `main` have not been modified.

## Observed defect, real behavior

The existing opt-in `run_dub(..., audio_mode="overdub")` validated a source-SHA-bound A4 partition, but still synthesized the entire translated subtitle script. The final `render_overdub` muted voices in `PRESERVE` and `REVIEW`, wasting synthesis and allowing an approved line to run into a protected exercise unless the next **translated** cue began there. Ultra-short merge units could be formed across an unreviewed interval. Resume also reused numeric `qwen_line_N.wav` paths after selection/approval changes.

Existing real lesson's saved legacy `overdub-approved.json` (not independently certified human exercise gold) contains **26 TRANSLATE intervals (194.88 s), 27 REVIEW (39.753 s), 0 PRESERVE**. All **32 of 32 existing Russian cues** lie fully within TRANSLATE; **zero real TTS calls are saved by this particular uncorrected plan**. This diagnostic is not a claim that the lesson has no vocal exercises. The stored plan is for a 234.633-second video-clock extraction, not the separate 234.684-second full-audio research WAV, and is not silently repointed to the latter.

## Narrow production change

- `app.audio.overdub.select_translatable_cues` consumes only the existing, source-validated A4 interval partition. A complete cue is eligible for TTS only if all of its sample-clock interval lies within contiguous `TRANSLATE` actions. If any part straddles `PRESERVE` or `REVIEW`, the **whole translated cue** remains original-only, with no automatic text splitting or assumption about which words correspond to which part. The full translated SRT is retained.
- Each eligible cue carries `dub_limit_s` from the exact A4 source-frame end. `_playable_usable_slots` applies that limit before take generation, scoring and pacing, and `place_lines(max_ends=...)` independently caps real audio at the same boundary, recording any resulting speech cut in the existing quality ledger. The user's existing 30ms clearance from the next dubbed onset and original video end still apply.
- Ultra-short merged TTS calls use an A4-region-specific merge key, preventing synthesis across distinct TRANSLATE regions separated by REVIEW/PRESERVE. Overdub disables automatic `fit_to_pace` rewriting of the filtered text because it would drop unvoiced lines from `translated.srt`; default replacement still uses its existing rewrite behavior.
- When **no** cue is eligible for translation, the Overdub runner creates an exact-duration silent voice bed and skips Qwen and synthetic-voice leakage checks. Original soundtrack/track remains selectable and undisturbed.
- A source/plan/text/reference/language/voice-mode/take-count SHA-bound selection fingerprint is required before resume can reuse previously numbered Qwen line files. The approval-plan SHA is rechecked after synthesis and before final mixing, preventing a stale A4 edit from silently applying during a long inference. Completion result includes selected and original-only cue counts and plan SHA, without duplicating private lyrics/translations in logs.

## Human A4 review, using the existing interface

The Overdub review modal now has a single **Next possible vocal exercise** control. After the existing **Suggest events with AST** action, it iterates over unreviewed non-speech hints, switches to the correct existing 100-row page, and plays the *original* source via the already implemented authenticated source player. It does **not** apply, confirm, export or relabel any A4 action; confidence is not presented as a probability. Existing manual Play / split / TRANSLATE / PRESERVE / REVIEW and confirmation remain authoritative. The new button is disabled when no suitable candidate is present. Korean and English control/message labels are supplied without another UI panel.

### Real 234.684-second source analysis

Performed one actual offline `MIT/ast-finetuned-audioset-12-12-0.447` run on the original 48-kHz source PCM (pinned AST weights already present, verified by the existing adapter). **117 four-second overlapping windows**. Leading group: 112 speech, 2 breathing, 2 coughing, 1 crying_baby. Mapping to the existing 2-second review bins yields five non-speech candidates for human listening:

| Original source seconds | Machine leading hint | Treatment |
| --- | --- | --- |
| 60-62 | breathing | REVIEW |
| 66-68 | breathing | REVIEW |
| 126-128 | coughing | REVIEW |
| 128-130 | coughing | REVIEW |
| 144-146 | crying_baby (raw top score ~0.081) | REVIEW |

**Not proof** that these intervals contain vocal exercises, and the speech-leading windows can also contain phonation/trills. Scores are uncalibrated; human hearing is required. No action was auto-promoted. Local source-bound model output and review queue with nearby English ASR text (kept out of Git):

`~/Documents/PersoDub-Research/reports/p1-a4-pretts-gate-20261103/ast-full-source-234s.json`
`~/Documents/PersoDub-Research/reports/p1-a4-pretts-gate-20261103/a4-possible-exercise-review-queue.json`

## Verification and remaining quality gate

Python unit/integration tests exercise whole-vs-crossing cue selection, adjacent approved speech spans, REVIEW-only no-TTS path, real 48 kHz protected-interval PCM identity, cap against generated overlong WAVs, unchanged replacement mode, no short-line merging across A4 boundary, invalidation of stale resume keys and rejection of a plan edited during synthesis. UI tests cover human-original player seek, 100-row page boundaries and manual-only model hints.

**Still NOT_RUN:** real native-Russian blind accent/voice reviews, independent human English/Russian semantic and singing/trill boundary validation, measured TTS time saved on an A4-annotated source. The original 24-clip research playback remains *partially dubbed and not independently human certified*. Qwen clone samples can still be chosen from source reference spans without independently human-verified phonation labels; do not claim a verified clean speech reference selection from this change.

**One next action:** listen to the five high-priority source intervals, then review other likely musical/vocal demonstrations (including speech-leading AST windows) in the original A4 player and explicitly save a source-bound human-reviewed TRANSLATE/PRESERVE partition. Only then rerun a genuine selective local TTS comparison against the 234.684-second original with native-Russian listening ratings.
