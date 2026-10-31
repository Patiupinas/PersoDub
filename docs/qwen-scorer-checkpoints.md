# PersoDub: Resumable pronunciation scoring for long-form dubbing

## Observed baseline (31 October 2026)

The owner's completed **Breath Control for TOTAL Beginners** local test is
234.684 seconds long. High Quality generated **32 lines x 4 takes = 128
candidate WAVs**. The existing scorer launched one faster-whisper-large-v3
CPU/int8 batch to transcribe every candidate for pronunciation comparison.
At approximately 19:44 local time, the scoring subprocess had been running for
more than nine minutes, consuming around four to five CPU cores. The entire
dub ultimately finished successfully (job `a45f8233`, status `done`), with
the leakage check, final video mux and preserved selected voice lines.

The old batch retained its results only in memory until every take had
finished. A process exit or timeout would require transcribing the whole batch
again, even if some takes had already been verified. The running-screen log
did not show intermediate progress.

## Implemented contract (this Draft PR)

- The local score-take worker receives optional `--checkpoint` and
  `--progress` arguments. Source STT without those arguments behaves as
  before; no model settings, beam width, target language or selection rules
  are changed.
- `qwen_scorer_asr_checkpoint.sqlite3` stores **one committed successful
  take per SQLite transaction**. Unlike rewriting a giant JSON checkpoint
  after each take, disk work remains proportional to the number of takes.
  A lost process retains previously committed candidates.
- Each cached entry is indexed by filename but additionally bound to the
  SHA-256 of the **current WAV bytes**. Its context includes target language,
  word-timestamps option, decoder policy, faster-whisper package version,
  model directory, weight-file size/mtime and the SHA-256 of `config.json`.
  Any context mismatch clears cached transcripts before new scoring. Failed
  takes are retried rather than cached.
- A resumed batch opens the installed model only when it encounters its
  first uncached take. Already-cached results reuse the same transcription
  text without loading the model.
- `qwen_scorer_asr_progress.json` contains only atomic aggregate counters
  `done`, `total`, `reused` and an update timestamp, never video names,
  text, transcript or paths. The server exposes those counters on an active
  single-job status response, with age and bounds validation; the desktop/web
  running screen shows `Checking pronunciation: X/Y`.
- The small progress file is deleted at the scorer boundary; the SQLite
  checkpoint deliberately survives a failed run or Resume. No new database
  server or external dependencies are required (Python stdlib `sqlite3`).

## Verification

- Pure unit tests for initial scoring, full reuse, source-WAV mutation,
  language/model mutation, interrupted work, retryable failures, malformed
  checkpoint, parent-worker CLI argument passing, cleanup, API privacy and UI.
- A **real offline Whisper Large-v3** run on two selected WAVs from the
  completed lesson produced two successful checkpoint entries. Running the
  exact same real worker and inputs again returned identical transcriptions,
  reported `reused=2/2` and exited in 0.06 seconds. This measures only cache
  replay of those two short files, not initial 128-take speed.
- Full repository regression results recorded in the draft PR.

## Still outstanding

A first-time Best-of-4 run must still synthesize up to four versions of each
translated line and evaluate their pronunciation with Whisper Large-v3 CPU.
The checkpoint improves observability and interrupted/resumed runs, but does
not claim to speed up a cold scoring batch. A safe later optimization should
benchmark voice quality, pronunciation accuracy, time-slot fit and total CPU
time against an independently reviewed sample before changing the shortlisting,
model or default quality policy. Hours-long lesson acceptance still requires
a real end-to-end replay with interrupted-stage recovery, not only synthetic
duration tests.
