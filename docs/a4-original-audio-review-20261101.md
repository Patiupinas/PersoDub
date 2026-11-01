# PersoDub P1-A/P1-B: source-audio verified observations and A4 listening

**Date:** 2026-11-01, Mac M1 Max. **Parent:** draft PR #39, `feature/vocal-asr-chunk-audit-20261101`. This is a separate reviewable change. No new translated audio was rendered. No job media, existing subtitles, approved A4 plans or main were overwritten.

## Source-first evidence, real 145-179-second vocal lesson interval

Source: finished job `a45f8233`, 234.684-second original `input.mp4` with SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`. Previous read-only source audit identified **106/731** zero-length word timestamps (not a translation error count). Eight bounded re-decodes on the installed Faster-Whisper Large-v3 gave **0/647** unique owned zero-duration words and a coherent replacement English source, but not human-verified truth.

This continuation decoded the **145.0-179.0s original PCM** separately with two architecturally different existing, locally cached models. **No new weights were downloaded.**

1. **Parakeet TDT 0.6B v3 / FluidAudio CoreML**, invoked as an isolated, research-only short phrase CLI built by the existing WhisperNotes repository. All required CoreML model files were present at `~/Library/Application Support/FluidAudio/Models/parakeet-tdt-0.6b-v3`; process log verified local load without a download. Full 34-second English output closely agrees with bounded Faster-Whisper Large-v3 on the instructions about transferring the exercise to a song, breath/throat management, inward/upward lower-abdominal movement, chest position and vocal power. Parakeet's CLI `confidence=1` is a hardcoded result placeholder, **not acoustic confidence**. The two models' agreement is corroboration, **not a human transcript certificate**.
2. **MIT AudioSet AST**, exact pinned model weights SHA-256 `d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918`, ran on the original stereo 48k PCM clip, 4-second observations every 2 seconds. All **16/16** windows chose the **speech** category as the strongest of the existing seven audio-event groups; singing's highest raw model score was **0.00109**. These scores are uncalibrated hints, not ground truth or permissions.
3. **Real app A4 preview** `_source_preview(..., analyze=True)` executed against the same finished job after fixing the stale local AST interpreter configuration. It returned `ast_observations`, `ast_available=true`, `requires_review=true`, **116 unapproved review segments** across the source video. Suggestions around 146-180 seconds are predominantly `speech`. A boundary observation around 144-146 seconds suggested `crying_baby` with a low uncalibrated score (**0.0814**); it was **not approved**. All 116 action fields remained `REVIEW`.

The existing old translation describes actions not supported by these two current source ASRs (for example an instruction not to lie on one's back and a request to remove a navel). The key failure is the old English transcript/timing that fed translation, not an audio encoder.

### Diagnostic translation contrast

A private, manually aligned **five-case** experiment compared the old Russian lines with *model-authored, unapproved* corrected Russian candidates, using the repaired English text as source. Exact SHA-bound inputs and all five full EN/RU pairs are stored locally, not committed.

- Multilingual MiniLM cosine chose the candidate **5/5**.
- Bidirectional multilingual NLI's minimum entailment chose the candidate **5/5**.
- This validates the ranking on **five selected contrasts**, not translation accuracy, calibrated adequacy, TTS naturalness or product release readiness. No candidate automatically replaces the original `translated.srt`. Independent human EN listening and RU adequacy ratings are **NOT_RUN**.

## A4 user-visible improvement

The finished-job **Overdub** review dialog had machine suggestions and an interval selector but did **not** let the reviewer hear the source directly in the same dialog.

The draft adds one inline, original-source `<video>` element and a **Listen** button for each interval, preserving the editor's existing bounded pagination for multi-hour jobs. Clicking Listen seeks the actual original media clock (with 0.4-second leading context), plays the source, and stops at the chosen event's end; users can also scrub and view the original video for context. The player is paused and its URL released on dialog close. Manual splitting and explicit `TRANSLATE/PRESERVE/REVIEW` decisions remain unchanged. Listening never sets `review_confirmed`, never updates A4 and never calls any translation model.

A restricted, completed-local-job `GET /api/dub/jobs/{jid}/overdub/source` endpoint streams **only** the original job `input.mp4` as inline MP4, with byte-range support for seeking. This avoids abusing the existing `/api/dub/result/{jid}/original` download/attachment route. The streaming endpoint does not create a new source file or expose arbitrary workspace paths.

English/Korean UI strings and responsive player/row styles were added. No new JS dependency.

## Local runtime correction

The Mac's `~/.persodub-dev-kit/kit.env` had `PERSODUB_AST_PYTHON` pointing into deleted `/private/tmp` research env. The only affected assignment was atomically replaced with `/Users/raymond/.persodub-dev-kit/engines_venv/bin/python`, an interpreter on which real AST inference succeeded. File ownership and mode `0600` preserved. The live AST model directory and model weights remain unchanged. This is a **machine-local setting**, not a Git artifact; no API keys were printed.

## Private evidence files (Mac)

All under `~/Documents/PersoDub-Research/reports/p1-a4-source-review-20261101/`:

- `source-145-179.wav`: exact original 34-second stereo PCM clip, used for the two independent model families.
- `ast-145-179.json`: 16 original audio-event observation windows, source WAV and model SHA.
- `parakeet-v3-145-179.json`: independent English transcript (not human-certified).
- `compare_translation.py`: reproducible local contrastive experiment with existing MiniLM and NLI models.
- `source-grounded-ru-contrast.json`: five exact old/candidate Russian comparisons and source/translation/model identity hashes.

Refer to `docs/chunked-source-asr-benchmark-20261101.md` for previous Large-v3 full lesson report. No private transcript/audio/model binary is included in Git.

## Verification

Source media and UI expected behavior are covered by focused API and Node tests, including a real byte-range request and source-byte identity, seek after split, playback stopping at event end, no implicit A4 approval, release on close, unknown/uncompleted job access denied. The canonical route inventory in `tests/test_routes_table.py` was explicitly updated to include the new scoped original-source endpoint.

Final exact-branch verification on Mac M1 Max:

- **Python full:** **2,665 passed, 5 skipped**.
- **UI Node full:** **1,146 passed**, including new source-player integration checks.
- **Desktop Node full:** **713 passed**.
- Ruff `app benchmarks tests`, Python `compileall`, `node ui/check-inline.mjs`, both locale JSON parsers, `git diff --check`: **PASS**.
- Three genuine model runs on source audio: AST original audio 34s (**16/16 leading speech category**), CoreML Parakeet v3 34s, and full-project AST review (**116 entirely unapproved hints**), all completed; local MiniLM and NLI finished for five source-grounded Russian contrasts.
- No GitHub Actions were started, no job output was overwritten, no A4 action automatically approved.

**Next action:** perform actual human audio listening through the new source player on 145-179s, resolve the uncertain 144-146s boundary and freeze the A4 source interval decisions; only then promote source repair and selectively regenerate Russian text and voice for known incorrect lines. Current model evidence alone is **OBSERVED** and not a reviewed event plan.
