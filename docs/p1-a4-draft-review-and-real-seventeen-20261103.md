# P1-G - source-bound A4 review drafts and real 17-cue Qwen validation

**Date:** 2026-11-03. **Branch:** `feature/vocal-a4-draft-resume-20261103`, stacked on Draft PR #48. No merge to `main`. The original lesson, project, user audio and licensed model weights have not been modified or checked into Git.

## Product behavior: users can finish A4 review across sessions

The existing, local completed-project A4 modal now has **Save review progress** and save-on-close. It stores a single project-local `overdub-review-draft.json` with all user split boundaries and selected actions, gain settings, original source PCM SHA and exact 48k sample count. **`review_confirmed` is always false in this file**. Closing or reopening cannot manufacture an approved A4 plan. Review/approval and existing mix/rebuild actions retain the existing human confirmation gate.

- Source-bound: a changed original PCM makes an old draft **stale**; the UI starts with all intervals `REVIEW` and shows that the earlier review belongs to a different source. It never silently imports old decisions into the new source.
- Versioned: saves use the SHA-256 of the stored draft bytes for optimistic compare-and-swap. Conflicting edits from another tab return HTTP **409**, and the earlier data remains unchanged. A valid new revision replaces the old file atomically via a private 0600 temporary file with flush/fsync/replace. The old file is not exposed by a download route.
- Single owner: draft endpoints and source-clock checking remain in `app.api.overdub`; plan parsing/revision and validation are in `app.vocal_overdub_review`. No browser localStorage duplicate is introduced.
- Reviewable context: the original-source video player now shows the overlapping original-language automatic SRT text and the current editable Russian SRT text from the same source project. Text is inserted via DOM `textContent`, not HTML, and never acts as an A4 classifier label.
- Fresh AST while editing: the existing classifier may be rerun without losing already split/marked intervals. A linear source-frame overlay preserves the exact saved **actions**, and incorporates new model hint edges, with no new approval. The 100-row paged UI remains bounded even for hours-long videos.
- The existing Quick Mix and Rebuild reviewed speech actions remain separate and unchanged; the default `replace` dubbing path still uses the prior contract.

### Real source/API regression found and fixed

The prior PR #48 added `singing_score` only to AST hints. `_compress` then indexed it unconditionally, causing the normal non-AST fallback `_source_preview(..., analyze=False)` to throw `KeyError` on adjacent same-hint transcript rows. A targeted test went RED on the original code, then GREEN after optional-field-safe comparisons. Real unchanged **234.633-second** source preview now returns **53** fallback review rows, **32** original-language and **32** Russian SRT cues in **0.336 seconds**, with the exact video source PCM SHA.

## Real Qwen experiment: 17 selected Russian cues, 15 original-only

Private Mac path:

`~/Documents/PersoDub-Research/reports/p1-a4-real-inference-20261103/`

Research-only output `research-seventeen-cues-20261103/dubbed.mp4`, **not** a fully reviewed release. The experiment uses the existing real source input with video SHA `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`, source-clock PCM SHA `e5687f71c121ea75fb1aa8d2da700e856cfd3b03ca7149e74e7c6e20702e4dfe`, 11,262,384 frames.

- Actual Qwen3-TTS Apple MPS 1-take synthesis for **17/17** selected cues completed in an overall **496.32 s** run, from cached original separation/ASR/script. It built only one SPK0 voice reference, not unused SPK1. Source was original-only for other **15/32** cues, with no model decision promoted to manual A4 gold.
- Full mux has selectable audio tracks `Overdub` and `Original`; **5,939,664 frames / 123.743 seconds** of REVIEW were PCM bit-identical with the original video source. All **7,039 original video packets** and **10,107 original AAC packets** are SHA-identical sequences.
- Independent, cached **Whisper Large-v3 CPU int8** readback from the 17 generated WAVs: **17 errors / 219 Russian reference words (WER 0.077626)**. This measures lexical recoverability, **not** Russian accent, same-speaker voiceprint, singing detection, source-to-Russian semantic fidelity or pause quality.
- Two translated speech clips were actually **cut short by 1.974s and 0.192s** at protected source-clock boundaries, despite the overall mux/packet QA PASS. These are voice-quality defects, not success evidence.

### Root cause in QA attribution

The Qwen assembly ledger uses a **one-based index in the filtered TTS selection**, while the UI script editor's lines are numbered against the **complete original SRT**. The real clipped results `line 11` and `line 14` actually referred to **source cues 26 and 29** (selected zero-based indexes 10 and 13), not to source cues 27 and 30. A first private research shortening therefore changed the wrong two source lines and still produced exactly the same two clipping reports. This discrepancy is now reproduced by a regression test.

The source-clock A4 cue selector now adds `source_cue_number` as provenance to selected cues without touching the complete user script. When Qwen clipping is recorded, `app.pipeline._a4_remap_clipped_source_cues` remaps `clipped_lines.json`'s public `line` to the true full-SRT line while preserving the original filtered `selected_line`. This is idempotent on resumed jobs and makes existing Script/Quality UI point to the actual editable source cue. Default `replace` audio remains unchanged.

Private correction trials for the clipping case use an isolated copy of the original selected job and **15 SHA-verified unchanged WAV clips** with only two specified text/voice candidates regenerated via a **private research wrapper** around the standard Qwen/Overdub runner. This is **not** the current production reuse feature: if its full script fingerprint changes, the released Overdub pipeline correctly invalidates all numbered WAVs. No private research edit writes back to the original project or claims human-approved Russian translation.

## Validation and limitations

Real source and clip identity have executable private reports, not public media. The attached project tests cover draft CAS, exact source mismatch, no auto approval, stale source reopening, close persistence, source/target transcript context, model boundary overlay, fallback no-AST KeyError, A4 original-SRT clipping index, and original replacement mode regressions.

Human A4 PRESERVE decisions for vocal demonstrations, native-Russian voice and bilingual semantic listening remain **NOT_RUN**. The 17-cue source with 15 REVIEW-only cues is exploratory, not a complete accepted dubbed lesson. The native-Russian blind A/B reviewer already exists and is described in `docs/p1-voice-reference-blind-review-20261101.md`. Do not treat ASR WER or machine singing score as a substitute for those labels.

**Next action:** complete original A4 vocal-interval listening/labeling and evaluate all failed/cropped Russian lines with a native-Russian reviewer, then use the existing Rebuild reviewed speech action for a truly human-authorized full-length Overdub. Preserve the original audio track and exact source packet identities.

## Targeted two-line correction and a ready-to-use A/B pack

A private research pass checked whether the above clipped lines can be fixed without spending eight more minutes generating all 17 Qwen clips. The first attempt erroneously interpreted the filtered ledger as full-SRT line numbers, changed **source cues 27 and 30**, and left the same two audio cuts. It is retained only as failure evidence, not a recommended output. The code fix above identifies the correct source numbers.

The corrected, source-bound experiment then changed only original **cue 26** to a shorter Russian phrasing about a working trill and insufficient airflow, and **cue 29** to a short instruction about pitch range and volume. It reused 15 WAVs whose SHA-256 matched the original 17-voice experiment and re-synthesized only these two lines. The **73.85s** run yielded zero clipped lines and a two-track MP4 with bit-identical protected-source PCM and source media packets. Independent cached RU Whisper heard 2 errors/11 words for new cue 26, but **3 errors/4 words** for the initial short cue 29. Therefore a zero-cut audio ledger by itself was **not** declared an acceptable Russian dub.

A final one-line experiment replaced **only cue 29** with a more easily spoken phrase about pitch and volume. It reused 16 already-generated WAVs with individual SHA checks. Real Qwen/MPS + full audio leakage gate + FFmpeg rebuild finished in **37.98s**. That new phrase was independently recovered by Whisper with **0/4 word errors** and no audio clipping.

The final private research video is:

`~/Documents/PersoDub-Research/reports/p1-a4-real-inference-20261103/research-seventeen-pitch-volume-variant/dubbed.mp4`

- Output video SHA-256: `97499e39e057ecbc4cf9d1cc017acfb711791151a591dc55235d59ebfac9a977`; original source video unchanged.
- **17 of 17** selected local Russian voices exist; **15 of 32 source cues** remain original-only because all source A4 decisions are still research, not human-certified.
- **0 clipped lines**; the full **5,939,664 frames / 123.743 seconds** in REVIEW are byte-identical to the source PCM. **7,039/7,039 video packets** and **10,107/10,107 original AAC packets** are SHA-identical. Output streams are separately selectable `Overdub` and `Original`.
- The new source cue 29 took **1.600s** and had **0/4** words misheard by independent local RU Whisper. Source cue 26's shortened phrase had **2/11** errors.
- A SHA-reconciled independent RU corpus report reused the **15 exactly unchanged** earlier WAV/transcription results and the two newly measured lines. On its **new 206-word reference script**, it yields **15 errors / 206 words, WER 0.072816**, versus the earlier **17/219 = 0.077626** with the older script. The denominators and two phrases differ; this is **not an iso-text native-accent improvement claim**.
- Private reports: `pitch-volume-final-technical-audit.json`, `pitch-volume-variant-independent-asr.json`, `pitch-volume-combined-independent-asr.json`, `corrected-clipped-technical-audit.json`.
- The research-only SHA-verified wrapper deliberately bypassed the **product's whole-script re-synthesis checkpoint** to reuse numbered files. This one-off reuse is **not a shipped user-facing partial-update capability** and has not changed core production cache behavior.

The existing `benchmarks.persodub.blind_review` was used to create an offline listening comparison of source cue 26 (previous clipped voice vs shorter voice) and source cue 29 (first unintelligible short phrase vs improved short phrase). For each case, the original source audio and two actual **final mixed Overdub** WAV excerpts were prepared. Random A/B assignments are private and separate from the pack; no human ratings have been generated.

- Reviewer page: `~/Documents/PersoDub-Research/reports/p1-a4-real-inference-20261103/two-cue-blind-listening-pack/index.html`
- Portable offline package: `two-cue-blind-listening-pack.zip` (approximately 2.6 MB) in the same private report directory
- Ratings template: `two-cue-blind-listening-pack/ratings_template.csv`
- Private answer key: `two-cue-blind-private-key.json`, outside the review pack with owner-only permissions
- **Status:** `OFFLINE_RUSSIAN_LISTENING_REVIEW_NOT_RUN`. A better ASR transcript does not establish absence of an English accent, speaker-voice similarity, pauses, emotional expression or faithful bilingual semantics.

### Exact branch verification

The final code/test tree was exercised on Mac with the full project suites: **2,784 Python passed, 5 skipped**, **1,160 Web UI passed**, **713 Desktop passed**. Ruff, compileall, inline-module checks, JSON parse checks and Git whitespace integrity also passed. Actual source fallback `_source_preview` verified on the full video. Synthetic clipped-original-cue mapping test went RED before the provenance fix, GREEN after. All original recording assets stay local.

**Next single quality dependency:** the user's actual listening-based A4 event decisions and native-Russian bilingual listening responses, not another heuristic for automatically certifying singing or pronouncing Russian.
