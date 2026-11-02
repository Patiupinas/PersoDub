# P1: match TTS scoring slots to the final audio placement clock

## Confirmed product defect

The existing Fast and High-quality Qwen paths passed `effective_slots(segments)` to TTS and take scoring, but the final `place_lines` assembler stops each line 30 ms before the next starting cue and at the original video's end. Overlapping cues could therefore mark a 1.8-second take as fitting a 2.0-second source cue, even when the actual playable interval was only 1.47 seconds. The final assembler then sped up and cut speech.

The Qwen path now computes one `_playable_usable_slots` value per line by intersecting the existing borrowed source slot with the same next-onset clearance (`END_HEADROOM_SECONDS`) as `place_lines`, and with the video duration when it is supplied. It follows the assembler's stable sort for nonmonotonic source cues. The same bounded slot is passed to all existing consumers: model request duration, Fast take checks, High-quality scored selection and optional pacing rewrites. No new TTS model, quality rule, translation or synthesis provider is introduced.

This is early **prevention of avoidable timing overruns**, not a guarantee of natural Russian. If no generated candidate fits or source speech conflicts irreducibly, the final cut is still recorded in the existing quality ledger (including fully skipped lines, fixed in the parent local commit `c979f54`). Existing completed user jobs are not rewritten.

## Exact verification

New contract tests cover overlapping cues, final video end, the unchanged 0.4 s borrowing cap where space permits, nonmonotonic input order, the real `run_qwen_dub` request receiving a bounded duration, and the already existing scored-take selector preferring a fitting candidate. The scored-take test uses fake scores; it is **not** a real Qwen speaker or acoustic-quality verdict.

Five real cached Qwen3-TTS Russian WAVs from the earlier 34-second research clip were rechecked without rebuilding speech, modifying the lesson, or human A4 approvals. All 5 still fit the physical slots; in one line the bound changed from 3.24 s to 3.21 s, and its generated voice is 3.12 s. The other four bounds were unchanged. Exact clip SHA hashes and per-line durations are in the Mac-only result:

`~/Documents/PersoDub-Research/reports/p1-placement-slot-20261102/real-five-russian-clips.json`

This five-clip check establishes absence of newly generated overruns on that sample. It does not establish improvement on the original 234.684-second job (which has not been regenerated), source-English correctness, exercise protection, native Russian pronunciation, speaker likeness or source preservation.

## Next working step

On the original 234.684 s video, approve a short mixed speech/exercise interval in A4, then synthesize a reviewed Russian sample with the bounded-source English transcript, bounded Qwen placement, separately selectable original audio and protected original exercises. Compare word readback, timing, speaker and pause perception before generalizing beyond four minutes. Source media, models and human-review CSV stay local.
