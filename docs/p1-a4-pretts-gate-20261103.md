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

## Follow-on: review singing evidence under speech-leading AST windows (2026-11-03)

Branch `feature/vocal-a4-singing-review-active-speakers-20261103`, stacked on Draft PR #47. The earlier "Next possible vocal exercise" reviewed only the **top** AST class per 2-second source bin. The saved real 234.684 s original-AST observation has 117 windows and 116 compressed review rows: five rows have a non-speech top class, while **six more speech-leading rows** at 14-20 and 22-28 s have independent nontrivial singing signals (raw model group score 0.041-0.146). Before this change, the UI could not navigate to these six cues.

The backend now retains `singing_score` separately from the winning `hint` and `score`. When `hint="speech"` and `singing_score >= 0.04`, it sets only **`suggested_action="REVIEW"`**, not TRANSLATE or PRESERVE. The threshold is strictly a heuristic for review priority, not a calibrated probability, diagnostic gold or automatic A4 action. The existing "Apply suggestions" button consequently **leaves these ambiguous speech/singing intervals unapproved**; the existing Next control can seek the original source and displays the separate raw singing score. The only authority for translation/exercise preservation remains a manually chosen A4 action. All other source-bound timestamps, original PCM hashes and source videos are unchanged. English and Korean text use existing locale infrastructure. The existing multi-hour paged review stays bounded.

The saved AST report for 234.684 s `source-original-48k.wav` has SHA `94eeea9d834d91d7bfb2c89551b7b053cbee22399e0ec7564853a7b0090e8cf4`; **this is not** the different 234.633 s production-video-cut hash `e5687f71c121ea75fb1aa8d2da700e856cfd3b03ca7149e74e7c6e20702e4dfe`. Keep source clocks distinct when rerunning or importing reviews. The six newly queued intervals and the original five are research observations; none have been human verified. Private results: `~/Documents/PersoDub-Research/reports/p1-a4-real-inference-20261103/secondary-ast-review-summary.json`.

Separately, real Qwen evidence on this same source revealed unused speaker reference cloning: all four selected translated lines were `SPK0` but the previous TTS run cloned `SPK1` as well, using a 1.08 s source span. `run_qwen_dub` now clones only source speakers actually assigned to the selected TTS segments. It still uses the whole source transcript for speaker attribution and original voice sample extraction, and clones every active speaker in true multi-speaker output. This reduces wasted cloning and removes an irrelevant short voice reference; it does **not** establish voice similarity or native-Russian quality. The original four-cue media and real voice quality remain as documented in `docs/p1-a4-real-qwen-clock-fix-20261103.md`.

**One next action:** listen and confirm the real source's overlapping speech/phonation bins in A4, then run the full real selective voice generation and native-Russian blind listening. No model-created action is a substitute for that review.

### Exact production-video AST integration verification

Executed the actual `app.api.overdub._source_preview(..., analyze=True)` with `PERSODUB_KIT_DIR` pointing to the local Desktop Kit. The configured AST Python and model snapshot both exist; checkpoint weights SHA matches the code-pinned SHA. The model call returned `analysis="ast_observations"` for the **234.633 s video-cut**, original source PCM SHA `e5687f71c121ea75fb1aa8d2da700e856cfd3b03ca7149e74e7c6e20702e4dfe`, **11,262,384 frames**. It produced **116** source-clock review rows and the same six speech-leading secondary-singing candidates as the separate 234.684 s research WAV. All six have `action=REVIEW` and `suggested_action=REVIEW`. The temporary source PCM and AST artifact were cleaned after the request; private parsed results are at `~/Documents/PersoDub-Research/reports/p1-a4-real-inference-20261103/production-video-a4-preview-exact.json`. The model inference is evidence that the interface can navigate the regions, **not** evidence that they truly contain singing.

Validation on this branch (Mac, Python 3.11): `pytest tests` **2,778 passed, 5 skipped**; web UI **1,152 passed**; Desktop **713 passed**; Ruff, compileall, inline module validation, both locale JSON parses, and `git diff --check` PASS. This is source-based behavioral and integration evidence. Human A4/vocal-exercise labels and native-Russian listening PASS remain `NOT_RUN`.
