# PersoDub Vocal Dubbing: AI Agent Entry Point

Scope: the user's local-first EN/DE/ES to Russian vocal-lesson dubbing research and product work in this fork.

1. Read [the execution plan and handoff](docs/vocal-dubbing-agent-handoff-20261101.md) before changing vocal-related code.
2. Read `docs/development.md`, `docs/architecture.md`, `docs/persodub-benchmark-program-20261031.md`, `docs/vocal-overdub-dual-track.md`, and `docs/s2st-lab-ui-20261101.md`. Inspect the current source and PR stack: written status is not runtime evidence.
3. Read `docs/p0-overdub-real-export-20261101.md` and `docs/p0-quality-report-and-mixed-validation-20261101.md` for the real P0-A/P0-B evidence, UI QA and mixed technical export. Next: independent human-reviewed A4 speech/singing intervals; do not add another model first.
4. The only final translate/preserve authority is **A4**. Model guesses never become human ground truth. Preserve protected vocal demonstrations, exact source clock, the original stream, and user media.
5. Reuse project-owned FFmpeg/mixer, S2ST Lab, Qwen and benchmark components. WhisperNotes is source-code reference, not an external service.
6. Use source-bound, independent evidence for event detection, Russian accent, speaker identity, semantics, timing, mixing and multi-hour processing. See `docs/translation-quality-benchmark-20261101.md` for local semantic triage. Report `NOT_RUN` truthfully.
7. Do not add GitHub Actions, bulk-download datasets or merge to `main`. Make focused reviewable commits on separate branches, do not publish private media or model weights.
8. At handoff, record exact commit/tree, branch, runtime/hardware, tests actually run, current defects, and **one next action**. A prior PR's PASS does not apply to a new commit.
