# PersoDub Vocal-Lesson Dubbing: Execution Plan and AI-Agent Handoff

**Snapshot:** 2026-11-01 (Europe/Madrid). **Scope:** the user's EN/DE/ES to Russian, local-first, vocal-instruction dubbing project. This is an execution handoff, not proof that an implementation has passed release acceptance.

**Canonical repository:** https://github.com/Patiupinas/PersoDub (the user's fork, not stronghamjji/PersoDub).
**Implementation baseline at this snapshot:** Draft PR #32, `feature/vocal-s2st-ui-20261101` at `f6cb147f15b9ee70b39699f1410222ff7a8e29b7`.
**Docs-only continuation branch:** `docs/vocal-dubbing-agent-handoff-20261101`, based on the exact PR #32 head above. This document and root `AGENTS.md` are the only intended differences from that implementation snapshot.
**Main at snapshot:** `6309632532f10bc74ae90e68b36c1537c1a34fee`. Do not assume later refs remain unchanged; query Git before acting.

**P0 progress update, 2026-11-01:** See `docs/p0-overdub-real-export-20261101.md` on the P0 integration branch. Source-bound real-job baseline is reproduced (P0-A). PCM protected boundaries, Original stream-copy, source-audio tail duration and actual MP4 stream topology are fixed and verified on a 234.7-second all-REVIEW technical export (P0-B technical). Python 2,576 passed / 5 skipped, UI 1,138 passed, desktop 713 passed. This does **not** approve any translated vocal-lesson speech or resolve the reported Russian accent, 0.9-second SPK1 sample and truncated original Qwen job. The next task is to expose output-mode-specific QA in the finished-job UI and freeze independently reviewed speech/vocal boundaries.

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

6. Re-verify the P0-A real baseline and P0-B technical PASS from `docs/p0-overdub-real-export-20261101.md` against your **current commit and input hash**, then continue P0-B with finished-job output-mode QA and a genuinely reviewed TRANSLATE/PRESERVE export. Do not move directly to another neural model.
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
