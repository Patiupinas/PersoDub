# Antigravity CLI native Russian translation: opt-in adapter and source-bound review

Status: P1 experimental, Nov 3, 2026. Stacked on full original audio return
branch. No original film, translated scripts, private logs or model weights in Git.

## What is actually implemented

- `app/translation_antigravity.py`: optional `Antigravity CLI` provider using the
  existing project's translation engine interface. Explicit `--mode plan`,
  `--effort low`, structured CLI JSON, 4 source cues per request, adjacent
  source context, bounded timeout, immutable hash-derived per-prompt cache.
  Rejects `status=SUCCESS` with missing/empty `response` (actually observed).
  There is **no verified CLI model identifier** returned by this machine, so
  the model is recorded as unknown, never guessed.
- `app/translation_gate.py`: conservative Russian text selection criteria
  for a dubbed source-clock cue: Russian script present, source-slot length
  <=2.3 Cyrillic words/second, complete sentence, stable informal address
  (and optional known narrator grammar). Rejects flagged candidates before
  their SRT is committed for automatic TTS. These flags are **not** a semantic
  equivalence score and do not certify correct translation.
- Existing translation pipeline now uses the Antigravity provider's
  `translate()` directly instead of bypassing checks through generic
  `fit_translate(engine.ask,...)`; semantic review flags are **not**
  silently retried as malformed JSON.
- Existing engine capability registry, setup dropdown and generic translator
  factory expose it as opt-in. ChatGPT stays the default. No new dependencies,
  background daemons or model downloads.

## Real private experiment and corrected source conflict

Private report root on Mac:
`~/Documents/PersoDub-Research/reports/p1-argon-translation-20261103/`.

- A single 32-cue CLI request took 182s and returned
  `status=SUCCESS`, `response=""`, with zero usage counts. This is NOT
  successful translation.
- A default 4-cue request took 85.52s and spilled text across cue boundaries.
- A tighter prompt with low effort translated four cues in 9.18s with
  complete sentences. Eight 4-cue blocks generated 32/32 source-clock
  Russian cues in 53.35s, but 11 exceeded the time budget.
- The output is not independently bilingual reviewed. One definite grammar
  problem is source narrator's masculine past `I was supposed...` vs raw
  Antigravity `Я хотела` at cue 5. The script should not become approved
  on a generic language-model judgment alone.
- **Source conflict correction:** an earlier private analysis mistakenly
  called Antigravity cues 20/21 semantic errors. The frozen 32-cue English SRT
  actually says *get your muscles back* in 20 and *back muscles, tension in
  your belly button* in 21; those support parts of Antigravity's wording,
  not the ChatGPT baseline's instruction to work an exercise into a song.
  However, an *independent 74-cue bounded Whisper source ASR* around 140-147s
  says `work it through a song`, with a gap until 150.44s when it says
  `This is teaching your body how to manage the breath...`. Therefore the
  source ASR hypotheses disagree: neither translation is established as
  ground truth. The old hybrid's claim of three confirmed semantic errors was
  overstated and its 19:13 fallback decisions are **not** semantic truth.

The previously generated 206MB hybrid video
`persodub-argon-hybrid-32-bilingual.mp4` remains an experiment, not a
certified improvement. It voices 19 Argon and 13 ChatGPT candidate lines;
longest assembly cut 0.344s; all 7,039 original video and 10,107 original AAC
packets preserved exactly. It is not automatically rewritten by this work.

## Quality gate ownership and next proof

The deterministic gate rejects obvious bad form/timing and never claims that
absence of flags means semantic correctness. A semantic pass requires a
verified English source, independent Russian adequacy scoring with a calibrated
review protocol or actual bilingual source listening, especially on conflicting
140-150s and the sung alphabet passages. Keep rejected candidate text for
review; do not silently replace it with the old ChatGPT candidate, which also
has source-ASR defects.

Exact tests cover CLI empty-SUCCESS, timeout, isolated four-cue bounded
call, version-agnostic response format, cache, opt-in, final pipeline bypass
prevention, Russian source-clock budget and continuity review.
