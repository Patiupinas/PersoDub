# PersoDub Vocal-Lesson Dubbing: Execution Plan and AI-Agent Handoff

**Snapshot:** 2026-11-01 (Europe/Madrid). **Scope:** the user's EN/DE/ES to Russian, local-first, vocal-instruction dubbing project. This is an execution handoff, not proof that an implementation has passed release acceptance.

**Canonical repository:** https://github.com/Patiupinas/PersoDub (the user's fork, not stronghamjji/PersoDub).
**Implementation baseline at this snapshot:** Draft PR #32, `feature/vocal-s2st-ui-20261101` at `f6cb147f15b9ee70b39699f1410222ff7a8e29b7`.
**Docs-only continuation branch:** `docs/vocal-dubbing-agent-handoff-20261101`, based on the exact PR #32 head above. This document and root `AGENTS.md` are the only intended differences from that implementation snapshot.
**Main at snapshot:** `6309632532f10bc74ae90e68b36c1537c1a34fee`. Do not assume later refs remain unchanged; query Git before acting.

**P0 progress, 2026-11-01:** See `docs/p0-overdub-real-export-20261101.md` and `docs/p0-quality-report-and-mixed-validation-20261101.md`. Source-bound baseline reproduced (P0-A). Original audio/video stream integrity, protected fades and FFprobe topology verified on a real 234.7-second Overdub re-export (P0-B). The completed-job UI now has a read-only, output-mode-aware Quality check with Recheck and separate reviewed Overdub report. A real 8.55-second translated interval in a 234.7-second experimental mix preserves all 10,107 Original AAC and 7,039 video packets; the rest stays REVIEW, **not human-approved singing gold**. The existing Qwen job still shows the 0.9-second SPK1 sample, 5 overlong lines and 1.461-second truncation; none are solved by a good mux. **Next: independent human review of speech/vocal event boundaries and objective plus listening QA of the user-started redub.**

**P1-B translation-QE update, 2026-11-01:** A separate local reference-free EN/RU similarity benchmark and time-aligned report were executed on both real job copies. See `docs/translation-quality-benchmark-20261101.md` for measured data, model SHA and reproduction. Both Russian subtitle file hashes are identical, so no translation improvement can be inferred from the redub. At that earlier snapshot, COMET and independent bilingual adequacy were NOT_RUN. The later P1-B continuation below records the subsequently executed COMET-QE experiment; independent bilingual adequacy remains NOT_RUN. All model scores are OBSERVED only.

**P1-B metric-validation continuation, 2026-11-01:** Research-only, synthetic EN/RU contrastive probes and a real source-bound follow-up are in `docs/translation-contrastive-controls-20261101.md`. On 20 model-authored controls, MiniLM preferred the faithful text 17/20; bidirectional NLI and ungated COMET-QE each scored 16/20. A narrow, explainable EN/RU cardinal/music-key reviewer raised MiniLM-plus-fact coverage to 18/20 with zero faithful-control flags, without claiming real-world accuracy. All methods remain OBSERVED, not PASS. Next: independent bilingual natural-lesson annotations and a valid distant-paraphrase control; do not train/tune a global quality threshold on these synthetic checks.

**P1-B source-ASR grounding, 2026-11-01:** The next experiment is documented in `docs/source-asr-grounding-20261101.md`. Direct-source Whisper base and small independently re-decoded 8 low-ranked EN/RU intervals on the real 234.684-second lesson. Original `transcript.json`: 106/731 zero-duration word timestamps, 12/41 source cues flagged by additive read-only Quality check. One 145.64-146.72s segment has 16/18 collapsed word times and substantial model disagreement; one 171.72-181.20s interval may contain a preserved /brrr/ demonstration mixed with speech. A separate Whisper Base failure at 116-125s was not misclassified as a source event. Local reports include eight review intervals with empty independent-human annotation fields; no transcript or media was published to Git. A4 remains the sole translate/preserve authority. Next: isolate the original large-v3 long-form word-alignment failure and freeze real speech/vocal event boundaries before rerunning translation QA.

**P1-B bounded source decode continuation, 2026-11-01:** See `docs/chunked-source-asr-benchmark-20261101.md`. The exact installed Large-v3 checkpoint (Faster-Whisper 1.2.1, CPU int8, 34-second windows with 5-second overlap) decoded all 8 windows of the real 234.684-second source. Original saved transcript has 106/731 zero-length word times. New source has 0/759 zero-length raw word times, or 0/647 after assigning overlap once to disjoint cores. All 7 adjacent overlaps were checked, with no unresolved lexical review flags after normalizing ABCD versus A, B, C, D. This is technical source evidence, not independently heard English transcript gold, human singing/speech labels, or proof of good Russian dubbing. Research-only code has per-chunk timeout/checkpoint/resume, no source media or model weights in Git and no change to product A4 or `main`. Next: validate 145-179s English against original audio and freeze A4 vocal events before any source-transcription cutover.

**P1-A source original listening and independent confirmation, 2026-11-01:** See `docs/a4-original-audio-review-20261101.md`. The real 145-179s source was decoded by already cached CoreML Parakeet TDT 0.6B v3 (a distinct architecture) and compared with bounded Large-v3; their English transcripts agreed closely, exposing concrete semantic errors in the old Russian subtitle. Pinned MIT AST independently classified all 16 four-second excerpt windows as predominantly `speech`; scores are uncalibrated. The Mac's stale `PERSODUB_AST_PYTHON` kit.env path was replaced with its functioning existing local interpreter, and the actual app's source preview now returns 116 all-`REVIEW` A4 hints. The existing A4 editor now has a source-only player and a Listen button per interval, seeking on the original 48k clock through a scoped inline byte-range API. A private real 5-case Russian comparison found both MiniLM and cross-language NLI ranking corrected candidates above the old dubbed text (5/5 each), but corrected RU was model-authored and **neither source audio nor bilingual translation has human-reviewed ground truth**. No existing job or `main` was changed. Next: human listen to 145-179s and freeze A4 boundaries before any selective re-dub.

**P1-B opt-in production STT bridge, 2026-11-01:** See `docs/source-asr-bounded-product-pilot-20261101.md`. Product Whisper now has an explicit bounded-original-source decoder (34s observations/5s overlap, source-word midpoint ownership, EN/DE/ES opt-in, no change to take-scoring or default one-shot). A full real 234.684-second English source run returned 647 words, 0 collapsed word times and 3 timing-review cues; the old job's 731 words included 106 collapsed and 12 flagged source cues. Independent same-model research run matches the 647 owned word sequence exactly; independent Parakeet-v3 supported the repaired 145-179s content. Downstream scripts form 27 rather than 32 proposed dialogue slots. Source-ASR mode and language are recorded on transcript checkpoints so a Resume cannot reuse a stale translation against a different ASR source clock. This is an opt-in product candidate, not human-certified English or accepted Russian speech; no user media, original dubbed job, A4 actions or `main` were changed. Next: a source-corrected 34s RU preview with real Qwen and audible original bed, then compare accented speech and timing before wider activation.

**P1-B native-Russian blind panel continuation, 2026-11-01:** See `docs/p1-voice-reference-blind-review-20261101.md`. The real Mac now has a controlled three-configuration Qwen comparison on the corrected 145-179s Russian research text: old/trills-topic reference + timbre (1/25 independent ASR word errors, 0/3 time overruns), new speech-dominant 158.78-165.34s reference + timbre (0/25 errors, 1/3 overrun), and the same new reference + ICL (1/25 errors, 0/3 overruns). These metrics cannot select native accent or likeness. The existing blind-review CLI now makes an offline HTML A/B/source audio player with local CSV export and a separated private key, including voice-only no-original-bed N/A, plus a scored-results command that refuses fake complete panels. Six real blinded pair recordings exist on the Mac; native-Russian human panel ratings remain NOT_RUN. Next: obtain three genuinely independent native-Russian ratings, then select model/reference after hearing and review the full-lesson A4 source events. Neither A4 nor `main` changed.

**P1-B external quality benchmark continuation, 2026-11-02:** See `docs/quality-benchmark-shortlist-20261102.md`. Verified native-RU TTS and vocal benchmark candidates (CV3-Eval, GTSinger, VocalSound, MuST-C and gated FLORES+), plus source-provenance and licence constraints. Reused 60 already cached FLEURS `ru_ru` test recordings on the Mac, selected 8 with fixed seed and verified original transcripts, and completed actual offline Faster-Whisper Large-v3 inference: **WER 5/142 = 3.52%, CER 5/876 = 0.57%**, source- and model-SHA bound. Other datasets remain NOT_RUN; a clean Russian ASR benchmark alone is not native Russian cloned speech, vocal-boundary or semantic PASS. No additional model/dataset downloads, A4 decisions or main changes. Next: independent native-Russian blind listening of the six real Qwen variants and real A4 source-event gold before claiming product quality.

**P1-B cross-language voice similarity verification, 2026-11-02:** See `docs/p1-crosslanguage-speaker-sim-control-20261102.md`. Ran nine real Qwen-generated Russian WAVs (three matched target texts, old-reference timbre vs clean-reference timbre vs clean-reference ICL) through cached independent WavLMForXVector CPU speaker embeddings. Mean source cosine 0.749552 / 0.790715 / 0.836450 respectively, but **8 of 9 generated clips scored closer to an unrelated-corpus Russian FLEURS voice than to the mean of two English instructor references**. No speaker-similarity configuration winner is valid. The source-old/source-clean positive cosine is 0.932649, while EN source to FLEURS RU 0.609644/0.676043, suggesting cross-language/domain confounding. Product benchmark returns OBSERVED + CONFLICTING_LANGUAGE_OR_SPEAKER_PROXY, not PASS. No new weights, jobs, user media or A4 approvals. Next: official ERes2Net or another independently cross-language-controlled speaker metric, plus genuine native-RU listening and A4 human-gold intervals before voice selection.

**P1-B physical TTS slot alignment, 2026-11-02:** On the local Mac continuation branch, the existing TTS/High-quality selector now receives the assembler's real next-onset (30 ms clearance) and video-end bounds rather than accepting a longer overlapping cue interval. It reuses the existing candidate scoring and pacing mechanisms; no extra model, automatic vocal A4 approval or production cutover. Six new contract tests, a five-real-WAV no-new-overrun measurement, and a traceable local report are documented in `docs/p1-placement-bound-take-selection-20261102.md`. The parent commit `c979f54` also records completely skipped synthesized lines in the existing QA ledger. No corrected full-lesson media has been produced; native listening and A4 human gold remain NOT_RUN. Next: a short A4-approved mixed speech/exercise pilot with independent acoustic QA, then full 234.684 s regeneration.

**P1-B four-minute research-playback continuation, 2026-11-02:** See `docs/p1-four-minute-research-preview-20261102.md`. The original 234.684-second video has two separate full-length **unapproved** listening candidates with five repaired-source Qwen RU speech clips, two selectable audio streams, and exact packet-hash checks of all 7,039 original video packets and 10,107 original AAC packets. A separate English+RU bilingual-subtitle variant also exists. To avoid overwriting protected original audio, full 48 kHz source PCM is the mixer authority (a previous 34-second cut was not byte-identical). An additional corrected-source Russian speech-only synthesis experiment is kept private and must not be promoted to human A4 action gold or native accent PASS. Next: review the full-length candidate and the exercise boundaries on source audio, then accept only verified speech intervals.

**P1-B source-exact four-minute 24-clip result (2026-11-02/03):** See `docs/p1-four-minute-research-preview-20261102.md` and Draft PR #44 (`feature/vocal-full-lesson-preview-20261102`). Further research generated 19 source-bound RU speech draft clips, shortened selected overlong translations, and combined them with the prior 5 clips for **24 all-slot-fitting research-only inserted voices**. An old candidate's one-second-early onset was corrected to the true 169.36-second source time, and selectable Russian subtitle times now derive from actual placed PCM frames rather than old nominal timbre durations. Source AAC packet SHA comparison 10,107/10,107 and video packets 7,039/7,039; original PCM outside research speech is 122.124083 s byte-identical. Independent RU Large-v3 readback WER 7/232=3.0172%, **not accent/voice/semantics PASS**. Preferred local result: `reports/p1-full-lesson-research-20261102/breath-control-234s-corrected-24-verified-bilingual.mp4` (under `~/Documents/PersoDub-Research` on Mac). Both audio tracks + EN/RU subtitle tracks verified. Human A4 exercise gold, native-RU blind panel and faithful bilingual semantics remain NOT_RUN. **Next one action: human source-bound A4 review plus native-RU/translation listening of this exact 24-clip private candidate**, not more speculative models.

**P1-C source-validated A4 pre-TTS gate and direct original-source review (2026-11-03):** In `feature/vocal-a4-pretts-gate-20261103`, stacked after Draft PR #44, the opt-in Overdub path now selects only whole A4-approved TRANSLATE cues *before* Qwen; prevents placement and merge across protected source intervals; refuses stale A4/line resume; and leaves REVIEW-only jobs as selectable original-only mixes. Full translated SRT and normal replace mode remain intact. The existing A4 modal can jump directly to AST-nominated unreviewed possible vocal exercises and plays the original video without auto approving. Original full-lesson AST 117 windows produced five priority bins at 60-62, 66-68, 126-128, 128-130 and 144-146 s (all REVIEW, model only); results are private. Crucially the old 32-line A4 plan has zero PRESERVE entries and yields **zero synthesis savings** until true human vocal-example intervals are reviewed. See `docs/p1-a4-pretts-gate-20261103.md`. Next: human A4 source exercise review plus native RU semantic/voice listening, not new models.

**P1-F A4 speech-leading singing review and active-speaker cloning (2026-11-03):** Branch `feature/vocal-a4-singing-review-active-speakers-20261103`, stacked on Draft PR #47. A4 now keeps a separate raw AST `singing_score` for speech-leading bins, surfaces it using the existing original-source review navigator, and leaves secondary singing hits (heuristic >=0.04) at `suggested_action=REVIEW` instead of proposing TRANSLATE. On the frozen 234.684 s AST study this adds six unapproved review candidates at 14-20 and 22-28 s to the existing five top non-speech candidates. Qwen3-TTS now clones only speakers used by translated cues: the real four-cue pilot had exclusively SPK0 but previously cloned both SPK0 and 1.08 s SPK1. Human labels, native-RU accent, translated semantics, and full lesson synthesis remain unverified. Details and source-clock separation: `docs/p1-a4-pretts-gate-20261103.md`. Exact Desktop Kit production `_source_preview(..., analyze=True)` also PASS on the 234.633 s source with 116 rows and six secondary singing REVIEW suggestions. Python 2778 passed/5 skipped, UI 1152 passed, Desktop 713 passed; native-RU/A4 human review still NOT_RUN. No model output promoted to human A4 gold.

**P1-E real Qwen A4 run (2026-11-03):** After Draft PR #46, the actual four-minute lesson exposed a **51.083 ms all-zero separator-tail** exceeding the old 50 ms Overdub mixer tolerance; all four real Qwen voices had already been generated. Branch `feature/vocal-a4-silent-tail-20261103` fixes this by trimming only bounded byte-zero 50-250 ms tails after validating the source clock. The real trial then yielded a 234.684 s MP4 with two selectable audio tracks; all 207.543 s outside four conservative dialogue cues are PCM bit-identical to the original, plus packet-exact video+original AAC copy (7039+10107). Four-cue independent RU readback WER 1/58; **no human A4 or native accent/voice acceptance**. See `docs/p1-a4-real-qwen-clock-fix-20261103.md` and private Mac report `reports/p1-a4-real-inference-20261103/`.

**P1-D current work (2026-11-03):** `feature/vocal-a4-regenerate-20261103` connects the A4 review modal to the *production selective-TTS job*. **Mix saved voices** remains the old quick remix; **Rebuild reviewed speech** creates a new queued/trackable job with the same explicit reviewed plan. Only source video, full current source+translated SRT, original separation + transcript caches are copied, never old synthesized WAVs. JobStore retains Overdub mode and origin across restart, while source preflights and strict frozen-cache reuse prevent accidental ASR/translation rework. A synthetic real-FFmpeg MP4 integration path confirmed 2 tracks and protected original PCM using stub voice audio; human/native-Russian and real Qwen results remain `NOT_RUN`. Details: `docs/p1-a4-regeneration-connected-20261103.md`.

**P1-G A4 draft resume and real 17-voice QA (2026-11-03):** Branch `feature/vocal-a4-draft-resume-20261103` atop Draft PR #48. A4 editor now saves unconfirmed source-hash-bound manual splits/actions/gains to atomic CAS-protected project draft; reopening restores with confirmation OFF, AST reruns preserve/manual boundaries, source EN + draft RU text appears by original playback. Fixed source transcript-only preview `KeyError: singing_score` (actual 234.633 s source returned 53 bins, 32 EN/32 RU cues in 0.336 s). A research-only Mac Qwen run built 17/17 selected clips in 496.32s, preserved 123.743s REVIEW source PCM and original 7039 video/10107 AAC packet hashes; independent RU Whisper 17/219 WER. Two original source cues 26 and 29 clipped by 1.974/0.192s. Corrected filtered Qwen one-based selection line vs full original SRT line QA attribution; a targeted private revoice trial is separate from production and not a human-accepted result. See `docs/p1-a4-draft-review-and-real-seventeen-20261103.md` and private reports under `reports/p1-a4-real-inference-20261103/`. Full human A4, native RU accent and semantics remain NOT_RUN.

**P1-G latest real audio result (2026-11-03):** Correcting the actual original SRT cues **26 and 29** eliminated both prior 1.974/0.192s voice cuts. A second RU wording for cue 29 reduced independently heard errors from 3/4 to 0/4, still not a native voice quality certification. With 16 individually SHA-validated reused WAVs, 1 newly generated and 37.98s full rebuild, the private `research-seventeen-pitch-volume-variant/dubbed.mp4` has 0 cuts, 123.743s source PCM equality and packet-identical 7039 video/10107 original AAC. SHA-reconciled RU ASR on all 17 voices is 15 errors/206 revised words (WER 7.28%); two target texts differ from previous run. Offline blind two-cue listening pack exists at `reports/p1-a4-real-inference-20261103/two-cue-blind-listening-pack/index.html` with private key outside; genuine human ratings NOT_RUN. All technical details: `docs/p1-a4-draft-review-and-real-seventeen-20261103.md`. The partial WAV reuse is a **private controlled research-only wrapper**, not a shipped product feature.

**P1 latest owner priority and implementation (2026-11-03):** Natural Russian pronunciation is now the first-quality gate. Several consistent male/female fixed Russian voices for long multi-speaker lectures outrank source-timbre cloning (future optional research). Current stacked branch `feature/p1-ru-voice-diarization-20261103` adds separately source-bound >=0.80 CAM++ cosine **dubbing voice grouping**, complete-link, no source speaker rewrite; 5 fixed native Silero RU v5.6 voices, same-engine start/retry/revoice, in-app model selector+hash-pinned download, independent full real Mac audio. Real matched-Russian-script ASR on 17 cues: Qwen clone 15/206 (7.28% WER) vs native Silero 7/206 (3.40% WER). Real 234s native video completed in 21.45s; source video/AAC and 123.743s original protected PCM unchanged. A/B pack for human accent/naturalness ratings made, human ratings NOT_RUN. Silero v5.6RU official weights are CC BY-NC-SA (research/opt-in only, not commercial production). Critical readable handoff: `docs/p1-native-russian-voices-and-diarization-20261103.md`. WhisperNotes is inspected read-only as conceptual reference; its cosine thresholds are not calibrated percentages. Do not confuse source speaker IDs and output dubbed voice groups.

**P1 full source speech coverage implementation (2026-11-03):** Owner listened to the earlier native-Russian clip and detected many untranslated sections; source A4 research plan selected only **17/32** speech cues. New branch `feature/p1-full-speech-coverage-20261103` implements **source-clock speech coverage receipt** in pipeline/UI, explicit complete/partial/unknown statuses and partial-job gap numbers. A new isolated research video voices **32/32 transcribed source cues** using one native-Russian Silero voice (one odd CAM++ source label retained but both assigned VOICE_01), corrects speech around 2:30-2:56, rewords four letter/music demo sentences, and retains full original audio via dual tracks. Final independent RU ASR: **7/358 errors, WER 1.96%**; 3 tiny line trims total 0.021s. Original source 7039 video/10107 AAC packets SHA-identical to the final bilingual MP4, 34.153s original PCM unchanged. Optional second MP4 preserves 11.88s additional tentative exercises (46.033s original PCM unchanged), but these AST-derived exercise masks are NOT human A4 gold. Strictly distinguish "32/32 transcribed speech cue coverage" from "every real spoken English word translated". Real path and verification: `docs/p1-source-speech-coverage-20261103.md` and private `reports/p1-full-speech-coverage-20261103/final-user-facing-files-qa.json`. Original media, model weights and private scripts remain local.

**P1-H mixer fix (2026-11-03):** The full 32-cue Silero Overdub left the first sung original sample at -16 dB for multiple seconds after the Russian voice stopped because mixing depended only on subtitle windows. Branch `feature/p1-fast-original-return-20261103` changes existing source-bound PCM mixer to detect voice-only WAV activity in 20ms chunks with short hysteresis and fast original-gain restoration. On the actual video new mix is sample-identical to original source by 22.20s, all the way through the sung example to 25.5s (previously ducked until 25.64s). Both real 206MB bilingual MP4s regenerated WITHOUT new TTS; protected original PCM and all 7039 video + 10107 original AAC packets remain identical. The second exercise-masked variant is still provisional, not human A4 gold. See `docs/p1-fast-original-return-20261103.md`; private source-bound receipts live in `reports/p1-fast-original-return-20261103/`.

**Antigravity CLI translation quality gate (Nov 3):** New opt-in staged branch `feature/p1-argon-quality-gate-20261103` adds bounded four-cue Antigravity CLI translator, empty-SUCCESS rejection, source-clock Russian pace/register review, and prevents direct `fit_translate(engine.ask,...)` bypassing the gate. See `docs/p1-antigravity-translation-quality-gate-20261103.md`. Real experiment 32 cues/53.35s with 11 over-budget; original 32-cue full call empty SUCCESS. Critically, earlier descriptions of cues 20 and 21 as *confirmed Argon semantic errors* were overstated: frozen 32-cue source ASR supports back/abdominal language, while independent 74-cue ASR says "work it through a song" around 140-147s. This source disagreement requires source listening. Do NOT promote old hybrid fallback decisions as gold.

**P1-K German/Spanish source-language verification (Nov 4):** The opt-in Antigravity translator now explicitly distinguishes German and Spanish source cues from English and preserves continuation across source ASR subtitle boundaries. Two real YouTube vocal lessons were decoded on the Mac (80 seconds each) and tested through the CLI. Extended private trials: German 22 cues / 69.74s with gate flags 16 -> 2; Spanish 12 cues / 34.82s with flags 4 -> 2. Remaining overlong Russian lines still require correction; source transcript and semantic quality are not human gold. See `docs/p1-de-es-translation-live-20261104.md` and the private Mac `reports/p1-de-es-translation-20261104/compare-de-es.html`. No full dubbed MP4 or main merge.

## 1. Mission and observable end state

Produce independently reviewable, natural Russian dubbing of local multi-hour vocal lessons, initially from English and German and later Spanish, with these independently verifiable properties:

1. **Singing and vocal exercises:** original singing, humming, pitch demonstrations, breathing exercises and other protected vocal events are unchanged, audible at source level and never replaced by guessed translated speech.
2. **Language and speech:** faithful Russian translation of instructional speech, pronunciation that sounds naturally Russian, not foreign-accented phonetics carried into Russian.
3. **Speaker and expression:** preserve the correct instructor/guest identity, recognizable timbre and appropriate affect, pacing, stress and intonation. Voice embedding similarity alone is insufficient evidence.
4. **Time:** sentence *and within-sentence* pauses are natural; no cut words, lost phonemes, shifted speakers or unwanted segment collisions.
5. **Overdub:** two selectable output audio streams, `Overdub` (original plus Russian with a smooth, event-dependent balance) and `Original` (untouched original). Original sound stays perceptible under explanations and returns to full strength during demonstrations.
6. **Subtitles and container:** source text, Russian text and bilingual subtitle outputs, with an eventual selectable-track MKV master, in addition to useful MP4 export.
7. **Operational scale:** real 2 h / 4 h / 6 h jobs with bounded CPU/GPU/RAM/temp disk, progress, stage checkpoints, restart/resume and correct exact-time/chapter assembly on supported macOS and Windows.
8. **Evidence:** reproducible tests using independent gold labels, acoustic measurements, Russian-native blind listening and preserved version/source identity. A job that reaches `done` is not, by itself, a quality PASS.

Scope exclusions: do not create a second decision engine; do not require an externally running WhisperNotes service; do not add GitHub Actions; do not bulk-download datasets; do not silently change the normal Qwen pipeline or merge to `main`.

## 2. Sources of truth and architecture boundaries

Read in this order after checking out the handoff branch:

- `AGENTS.md` (short project-specific entrypoint).
- `docs/development.md` and `docs/architecture.md` (actual app structure, integration points, canonical test commands).
- **This file** for owner goals, priorities, current limitations and handoff procedure.
- `docs/persodub-benchmark-program-20261031.md` and `benchmarks/persodub/stage_catalog.json` (scientific benchmark methodology, metric contracts and authority levels).
- `docs/vocal-overdub-dual-track.md` (source-bound event-plan contract, PCM mixing and export).
- `docs/s2st-lab-ui-20261101.md` and `docs/seamless-s2st-mac-experiment-20261031.md` (experimental S2ST implementation and measured cases).
- `docs/dub-quality-audit.md` and `docs/qwen-scorer-checkpoints.md` (real completed-job QA and resumable scorer).
- GitHub PR #25 through #32 and their **actual patches**, not only the PR prose. Earlier vocal A1-A7 draft PRs are dependencies/reference, not proof of integration.

Authority: current runnable source + exact revision + observed tests outrank old reports. Independent dataset/human ground truth outranks model-predicted labels. Leave missing tests as `NOT_RUN`, machine proxies as `OBSERVED` and quality failures as `FAIL`. Never promote an older PASS to another commit, machine or platform.

Functional ownership already established:

| Stage | Responsibility | Non-negotiable boundary |
| --- | --- | --- |
| A2 acoustic observations | Speech, singing, other vocal events and optional F0/phonation evidence from AST/INA/SMAD etc. | These are estimates, not final translation actions. Model scores are not calibrated probabilities. |
| A3 ASR/diarization | Word/phrase timestamps and speaker assignments, internally reused/ported from WhisperNotes source logic. | No dependency on launching WhisperNotes externally. Use source-PCM clock. |
| A1 semantic review | Investigate acoustically ambiguous spans with audio-language model evidence. | Experimental model prompts do not rewrite ground truth or event boundaries. |
| A4 action policy | Sole canonical authority for `TRANSLATE`, `PRESERVE`, `MIXED` or `REVIEW`. | Uncertain/protected spans are not automatically translated; preserve exact sample/time identity. |
| A5 / A7 export | Subtitles and original-preserving multi-track packaging. | Original can be selected without remix/recompression assumptions; inspect actual streams. |
| Qwen and S2ST synthesis | Alternative audio-generation providers, orchestrated under the same approved action plan. | Native RU accent, identity, semantics, slot fit and voice quality must be assessed separately. |

Do not confuse a classifier's whole-clip class with sample-accurate event boundaries. Likewise do not confuse correct playback, a complete model call or a two-track file with perceptual quality.

## 3. Implemented evidence as of snapshot (not fresh acceptance)

| GitHub draft | Actual work available | Still missing |
| --- | --- | --- |
| #25-26 | Existing mixer/muxer reused for two-track Overdub; AST speech/singing suggestions, review UI and explicit confirmation. | Gold-labelled timing, automatic full-event selection and high-quality end-to-end output. |
| #27 | Streaming AST (4 s windows, 2 s hop), paged review and export resource checks; synthetic six-hour time/large-list tests. | Real 2/4/6-hour end-to-end chapter-based processing and AST resume. |
| #28 | Per-take durable SQLite Whisper scoring checkpoints with live progress; exact cache hit replays. | Faster first-time recognition/scoring without regressing quality. |
| #29 | Read-only completed-job quality audit catches wrong audio mode, short speaker reference and actual clipped source slots. | Integrated job-end quality gate visible in regular UI; acoustic defects not fixed by the audit. |
| #30 | 13-stage benchmark catalogue, metrics, source fingerprinting and balanced blinded A/B pack generator. | Independent vocal-event gold, transcript/reference truth and native-Russian listening results. |
| #31 | Experimental Meta SeamlessM4T v2 audio-in/audio-out on real Mac MPS, source-bound 6-clip batch, timed QA and source-preserving 2-track previews; separate Seed-VC research. | Reliable semantics, native Russian, voice identity and generalization; production provider integration. |
| #32 | Opt-in S2ST Lab inside Overdub, source preview, explicit manual speech-only approval, async MPS worker, saved results and downloadable WAV/MP4. One real 4.02 s -> 3.46 s Russian clip tested. | Full-length use, native accent QA, automatic exercise identification, interruption handling, Windows inference. |
| #12-13 | Earlier Draft MKV 2-audio/3-subtitle exporter and subtitle-track work. | Rebase/integrate against current code and run real export acceptance. |

**PR #32 reported verification on Mac:** Python **2,572 passed, 5 skipped**; UI Node **1,138 passed**; desktop Node **711 passed**; Ruff, compile, syntax and diff checks PASS. Actual headless browser path through S2ST Lab and real two-track MP4 tested. These are historical measurements for that exact code tree, not a fresh result from an incoming agent. `main` remains separate.

**Concrete diagnostic input:** completed local job `a45f8233`, *Breath Control for TOTAL Beginners*, source length **234.684 s**, 32 source cues. Initial ordinary output was a **single-AAC-stream replace mode**, not requested Overdub. QA found a second-speaker reference **0.90 s** long associated with **18 English words**; **five** synthesized source-slot overruns (**3.14 s** total) and one actual **1.461 s** cut; **19** original pauses shorter by **1.84 s** total, and source-derived end-boundary MAE **1.321875 s**. These exact failures define the first regression case. Later experimental S2ST previews *did* produce two tracks; do not conflate those with the earlier initial finished output.

**S2ST research failure case:** a **1.08 s** source cue yielded **33.06 s** of generated audio with an invented subtitle-credit phrase according to independent RU ASR; the quality triage marked it for review, not insertion. Six short speech-cue experiments yielded three timing candidates, two overruns and one extreme hallucination. Meta's checkpoint is local and separately licensed; not bundled with app. Experimental Seed-VC timbre transfer remained outside the product branch.

**Open evidence gap:** there is no independent end-to-end proof yet of naturally spoken Russian, correct speaker identity, original singing protection, within-sentence pauses or real multi-hour performance. Small curated classifier pilots (such as AST 22/24 coarse-category agreement) are not event-boundary or real-lesson acceptance.

## 4. Prioritized execution plan

The priority is **one good, reproducible four-minute vocal lesson** before optimizing six-hour throughput. Keep implementation changes narrow and observable. Every work package below is a task boundary suitable for one successor agent/PR.

### P0-A: Recover the canonical code and baseline

- Check GitHub current refs and open Draft PR stack. Start from PR #32's implementation tree and inspect actual changed files and tests. Preserve original branch identities and do not modify `main`.
- Check local Git/worktrees and dirty state, identify exact source video, completed job and current model/runtime versions. Never infer quality from an old build or cross-machine test.
- Run focused and canonical test suites (section 6). Reproduce the existing failure metrics on completed job `a45f8233` before changing behavior. Preserve report, media source hashes and git SHA.
- Verify exact dependencies among #25-32; create a **separate integration branch** only after determining whether stacked changes duplicate, conflict or require refactoring.
- **Done when:** one pinned branch/tree, independent reproducible test manifest, baseline QA report, and written list of mismatches. No behavior change implied by this recovery step.

### P0-B: Make the requested Overdub the actual output

- Trace user selection from UI/API/job config to playback/render/export. Existing Overdub logic and FFmpeg exporter should be reused, not replaced.
- Re-export the existing completed Qwen job when possible, without new TTS; validate that the output has **two selectable, correctly identified audio streams** and an intact original.
- Reuse `app.dub_quality_audit` to surface a truthful post-export quality status in the finished-job UI. If the requested output differs from actual streams, return FAIL rather than `done / acceptable`.
- Add tests for replace versus Overdub, re-export from cached synth audio, source-bed gain around approved speech and exercise boundaries, actual FFprobe streams and source-video continuity.
- **Done when:** the source-bound four-minute job emits two independently selectable streams with the requested behavior, an unmodified Original track and an explicit quality result. No claim of native accent quality from this gate.

### P1-A: Freeze independent event, speaker and pause gold

- Select only a small source-disjoint group of files from labelled **RAVDESS**, **NUS-48E**, **VocalSet**, **FLEURS** and real vocal lesson excerpts as applicable. Reuse published annotations and original SHA; select human-reviewed internal 15-30 s lessons with mixed speech/singing.
- Build true time-aligned, sample-clock annotations of speech, singing, vocal exercises, breaths, laughter/other sounds, overlaps, speaker turns, words and **within-sentence** pauses. Store machine suggestions separately; a model's guesses are not gold.
- Split by speaker/video, freeze development and held-out sets before tuning. Keep source language separately identified: EN, DE and ES; Russian is target/review language.
- Score A2 candidate detectors (AST vs INA vs SMAD vs SenseVoice; semantic audio-language model as A1 adviser) with time-weighted F1, false translation of protected-event seconds and timing error. Require independent source truth.
- Evaluate diarization with real RTTM where available and manually checked identity around the suspicious SPK1; do not merge speakers simply because one reference is short.
- **Done when:** independent frozen gold, reproducible evaluator, per-dataset metrics and honest `PASS/FAIL/OBSERVED/NOT_RUN` reports exist; A4 policy remains sole action authority.

### P1-B: Fix reference, translation, Russian speech and natural timing

- Identify clean same-speaker reference segments, validate length, matching transcript, signal purity and single-speaker provenance. Re-score SPK1 in the real four-minute case.
- Run controlled **Qwen3-TTS vs SeamlessM4T v2**, then a separately isolated voice-conversion experiment if useful. Use identical source/target prompts where the interfaces permit; record confounders where not.
- Independently score semantics (human/reference), Russian readback (separate ASR, WER/CER), native Russian pronunciation, speaker/timbre similarity and expressive prosody. For perceptual scores, blind A/B with **at least three native Russian raters** per clip; do not substitute embedding cosine or an ASR backread for human accent ratings.
- Fix timing at the translation/synthesis/placement layer: preserve original gaps *inside* and between phrases; prefer shorter/reworked RU text, constrained generation or explicit reviewed retakes over clipping. Measure clipped words, pause deficit, overlap count and boundary errors.
- Evaluate performance cost of Best-of-4 and candidate shortlisting *after* quality is comparable, not by sacrificing quality silently.
- **Done when:** on frozen held-out clips the chosen provider has stronger native-Russian and voice-identity evidence, no newly clipped words and reproducible source-clock/semantic measurements. Record tradeoffs rather than claiming a universally best model.

### P1-C: Integrate event-aware Overdub

- Map approved A4 `TRANSLATE`/`PRESERVE`/`REVIEW` actions onto existing source-bound PCM mixer. Never let arbitrary AST/MOSS scores approve unknown exercises.
- For baseline speech balance the previous research defaults were **original -16 dB** and **Russian -2 dB**; protected exercises/uncertain intervals use **original 0 dB**, Russian off; **300 ms** smooth transitions. These are configurable experiment defaults, not a user-listening quality verdict.
- Do not run speech TTS on entirely protected segments. Exercise audio remains full level and source-accurate; do not introduce false silence or voice cuts at boundaries.
- Validate synthetic independent source/gain inputs (exact dB and preserved PCM) and real mixed lessons (listening and FFprobe). Keep unchanged standalone Original track.
- **Done when:** verified event-controlled mixing, correct fades and dual streams, with no translated singing or missing original vocal signal on held-out reviewed intervals.

### P2-A: Real long-form, resumable jobs

- Implement chapter-based decode, source-sample absolute clock and FFmpeg/mux assembly that survives single RIFF/WAV limits. Avoid full-length multi-track in-memory buffers.
- Persist approved event plan, AST segment results, ASR/diarization, translation, TTS/quality and mux checkpoints with source/model/config hashes. Resume only compatible work after restart; no repeated work due to an interrupted final stage.
- Move long AST analysis from a single synchronous request to a resumable progress-reporting worker. Control temporary disk, memory and GPU concurrency.
- Run actual independent **2 h, 4 h, 6 h** source files. Measure cold/warm wall time, RTF, peak RSS/VRAM/temp disk, time drift, missing/duplicated audio, source/subtitle continuity and cost of simulated interruption at multiple stages.
- **Done when:** real media passes all release-relevant checks at all three lengths on selected target hardware; synthetic six-hour clock tests alone do not count.

### P2-B: UX, output and platform acceptance

- Keep research `S2ST Lab` opt-in until it passes independent speech-only, translation, voice and timing acceptance. Make event review/editing, quality-report visibility, resumable status and failed-segment retakes accessible without a crowded UI.
- Integrate existing Draft subtitle/MKV modules rather than writing a second exporter: **source / Russian / bilingual subtitle streams** and selectable Overdub / Original audio. Preserve source video continuity and correct language/stream metadata.
- Build/run real packaged macOS arm64 and Windows x64 outputs. Confirm no dependence on the Mac's research-only model paths; Windows native inference is not implied by a successful Mac Metal run.
- Add DE and ES source-language exercises/test segments as separate gold/evaluation rows (not assumed identical to EN).
- **Done when:** reproducible install, full UI user journey and quality evidence on target platforms, correctly selected tracks and successful long-form export.

## 5. Independent acceptance protocol

Treat these as distinct checks, not a single averaged quality score:

| Aspect | Oracle / mechanism | Expected outcome |
| --- | --- | --- |
| Original singing/exercises | Human intervals + isolated/source PCM | Zero protected original time replaced; original track intact |
| Event/speaker classification | Independent interval ground truth | Per-class source-clock F1 and protected-event false positives on held-out files |
| Russian accent and naturalness | Native-Russian blind listening, independent speakers | Compare with frozen baseline, confidence intervals and pre-agreed acceptance limits |
| Voice likeness | Same-speaker original references + blinded ABX and embeddings only as diagnostics | Proper voice identity without transferring English/German/Spanish phonetics |
| Translation | Held-out bilingual human references, reviewer adequacy | Meaning faithful, terminology and examples preserved |
| Pauses/timing | Independently annotated phrase/word gaps + actual output | No clipped words, no missing protected source, reduced boundary/pause error |
| Mixing | Calibrated synthetic stems + real audio listening | Configured dB curves, audible original under speech, full source through exercises |
| Streams/subtitles | FFprobe + actual playable samples | Two selectable audio tracks and required subtitle tracks; correct metadata |
| Long-running | Real 2/4/6 h runs and restarts | Exact timeline, bounded resources, resumable without duplicate/lost segments |

Calibrate numeric thresholds on development data **before** evaluating independent held-out sources. Keep failed and `NOT_RUN` items visible. A source-derived proxy can diagnose a failure but cannot certify perceptual audio quality.

## 6. First actions and runnable checks for a successor agent

1. Read root `AGENTS.md` and this file. Inspect latest PR #32 and its parent chain for upstream changes.
2. Clone the **user fork** and switch to the *handoff* branch; this contains the PR #32 implementation snapshot plus this documentation. Create a new feature/test branch before writing code.

~~~sh
git clone https://github.com/Patiupinas/PersoDub.git
cd PersoDub
git fetch origin docs/vocal-dubbing-agent-handoff-20261101
git switch --track origin/docs/vocal-dubbing-agent-handoff-20261101
git status --short --branch
git rev-parse HEAD
git log --oneline -6
~~~

3. Check `docs/development.md` for interpreter/venv setup, optional installed model paths, and existing tests. The normal codebase uses FastAPI backend, Electron shell, local Qwen sidecar and per-model worker interpreters. Do not put heavy ML packages in the core backend venv.
4. Run focused tests for the intended change, then current canonical checks:

~~~sh
.venv/bin/python -m pytest tests/ -q
node --test ui/src/*.test.mjs
node ui/check-inline.mjs
(cd desktop && npm test)
.venv/bin/ruff check app benchmarks tests
.venv/bin/python -m compileall -q app benchmarks tests
git diff --check
~~~

Commands assume project venv and desktop dependencies are installed; use the actual environment described in `docs/development.md` and report any checks not run. Historical PASS above does not replace execution.

5. Find local source job `a45f8233` and verify exact file SHA and job-root path before running completed-job QA. Previously used commands:

~~~sh
python -m app.dub_quality_audit --work-dir /actual/job/path --expected-mode overdub --output /new/qa-report.json
python -m benchmarks.persodub.local_case --work-dir /actual/job/path --expected-mode overdub --output-dir /new/bench-case
python -m benchmarks.persodub.runner --manifest /new/bench-case/manifest.json --out /new/bench-report.json
~~~

Use actual existing completed files; do not invent data or call an empty test directory an evaluated case. Keep individual outputs in unique local paths, never overwrite the original.

6. Re-verify the P0-A baseline and P0-B technical/export/UI evidence from both `docs/p0-overdub-real-export-20261101.md` and `docs/p0-quality-report-and-mixed-validation-20261101.md` against your **current commit and input hash**. Automated mode-specific QA now exists. Continue with a genuinely human-reviewed full TRANSLATE/PRESERVE event plan and independent listening benchmarks, not another neural model.
7. Each new PR should record: base/head commit, exact source + weights/config SHAs, changed ownership boundary, focused and full checks actually run, baseline-vs-new metrics, real sample IDs and unresolved acceptance gaps. Keep a single current task/next action.

### Machine map as checked 2026-11-01

- **Raymonds-Laptop.local (Mac M1 Max, macOS arm64):** current working research environment, Apple MPS, model weights, source video and UI/manual playback. At snapshot the clean GitHub-head-equivalent worktree was `/private/tmp/vld-s2st-ui-publish-20261101` at `f6cb147f...`. A second local development worktree `/private/tmp/vld-s2st-ui-20261101` had a different parent commit; use verified Git tree identity rather than assuming identical commit identity. Temporary paths are not stable.
- **SunLight (Windows, RTX 4090):** CUDA candidate benchmarking and genuine Windows application checks; no prior Windows S2ST acceptance in #32.
- **streaming2 (Linux ARM64):** independent Linux/regression, dataset indexing and low-resource analysis, not evidence of a supported Linux desktop product.
- **localhost (Android Termux):** remote shell available, not a primary PersoDub target.

Desktop Commander remote command execution was confirmed on all four devices on 2026-11-01. Recheck availability on the day of work. Keep checkpoint/model data and user source video local, not in Git. Mac S2ST research configuration is documented in `docs/s2st-lab-ui-20261101.md`; do not assume installed checkpoint exists elsewhere.

## 7. Project-specific non-goals and maintenance rules

- **GitHub:** no new Actions for this project; never merge to `main` merely to finish a task; keep experiments and integrations reviewable on branches.
- **Source code reuse:** WhisperNotes is a *reference implementation* for code/algorithms to port behind PersoDub-owned contracts, not an external executable ASR dependency.
- **Single policy authority:** A4 alone decides whether an interval may be translated; AST/INA/SMAD/SenseVoice/MOSS are evidence, not a second approval path.
- **Data discipline:** only targeted, open-access dataset clips with published or independently verified labels; do not download whole corpora. Never commit originals, user media, TTS outputs, private rater assignments or model weights. Source/model revision receipts belong in reproducible metadata.
- **Dependency choices:** evaluate quality, hardware fit and licensing before adopting Meta Seamless checkpoints or GPL Seed-VC components into a redistributed product. The current research is separate from a shipping-model decision.
- **Product scope:** build the smallest viable complete path, not multiple competing synthesizers, mixers, annotators or export engines. Reuse current Qwen, PCM event policy, FFmpeg exporter, benchmark runner and UI patterns.

## 8. Required handoff record at the end of each agent session

Provide an update in the applicable PR or a versioned experiment report:

1. Exact date/time, machine/runtime, repository/ref and commit/tree SHA.
2. Task ID from section 4 and the user-visible behavior being changed.
3. Actual implementation files, boundary owners and important configuration/contract changes.
4. Tests/benchmarks executed now (with exit status and concrete input references) versus historical reports.
5. Evidence for protected vocal events, translation, Russian accent, timbre, pauses, mix and streams. For unverified items write `NOT_RUN`.
6. Remaining defect, independent evidence still needed and **one concrete next action** for the successor.
7. Local file locations that are *presently verified* plus note if they are ephemeral or machine-specific.
8. PR/commit link for the saved work; don't claim an unpushed local change is in GitHub.

### Ready-to-use successor prompt

> Continue the vocal-lesson dubbing work in Patiupinas/PersoDub. Fetch the latest P0 integration branch based on docs/vocal-dubbing-agent-handoff-20261101, read AGENTS.md, docs/vocal-dubbing-agent-handoff-20261101.md and docs/p0-overdub-real-export-20261101.md. Inspect the PR #32/33 stack and current source tree. Re-run relevant tests: historical PASSES are not transferable. P0-A and the technical stream-integrity part of P0-B were measured against the four-minute job a45f8233; continue P0-B with finished-job output-mode QA and independent human-reviewed TRANSLATE/PRESERVE event gold. Do not introduce more neural models before closing that gap. Keep A4 the sole decision authority, original singing untouched, no GitHub Actions, no bulk downloads and no changes to main without owner direction. Record exact measured results and one next action in the PR.
