# Read-only WhisperNotes Session Pipeline V2 importer

This module converts **existing** WhisperNotes JSON artifacts to normalized
source PCM observations. It never runs ASR, diarization, vocal classification,
TTS, or network access.

Verified source at design time: `Patiupinas/whispernotes@2f863db64f41680365a0f9f8772f9147034ea675`,
particularly `SessionPipelineV2Artifacts.swift`,
`SessionPipelineV2Models.swift`,
`PhraseCoherenceJudge.swift`, and `PhraseHighlightWordBuilder.swift`.

Required inputs: `session.final_transcript.json` and `session.phrases.json`.
Optional: `session.asr_candidates.json`; if absent, selected-candidate word
timings are not trusted and affected phrases are marked for review.

The decoded source PCM SHA-256, sample rate and sample count must be supplied
by upstream ingest. Time domain is **explicitly** `original` or `compact`.
A compact map must be supplied for compact input. The importer refuses
segments crossing removed compact gaps rather than silently shift cues.

The stable session-local speaker ID comes from `session.phrases.json`,
**not** the displayed speaker name in the final transcript. Selected ASR
candidate words are stored phrase-relative in WhisperNotes; this adapter
normalizes them to source PCM sample indexes and preserves `isEstimated`.
Rounded source seconds are not proof of sample-accurate ASR boundaries.

Usage:

```bash
python -m app.scripts.vocal_import_whispernotes \
  --session /path/to/existing/whispernotes/artifacts \
  --pcm-sha256 <decoded-source-pcm-sha256> \
  --sample-rate 48000 --total-samples 480000 \
  --time-domain original --output /local/working/transcript.json
```

Python API: `app.vocal_whispernotes.import_session(final, phrases, candidates,
pcm_sha256=..., sample_rate=..., total_samples=...,
time_domain='original')`.

No modifications to WhisperNotes. This is a component prototype, **not yet
wired into an actual PersoDub dubbing job**. On Windows the existing
PersoDub Whisper/CAM++ path remains the fallback. The schema accepts `es`
for future Spanish input; the current vocal decision policy does not.

Run: `python -m pytest tests/test_vocal_whispernotes.py -q`.
