# Completed-dub quality audit (first deterministic gate)

A successfully muxed MP4 does **not** establish acceptable translation,
speaker likeness, Russian pronunciation, preserved pauses, or source volume.
This narrow, read-only audit checks properties already measurable from the
finished source video, preserved speaker references, source cue times and
generated Qwen WAVs. It does not run another ASR, download models, synthesize
speech or modify a completed job.

Run on an existing job directory:

```sh
python -m app.dub_quality_audit \
  --work-dir /path/to/workspace/YYYY-MM-DD/project \
  --expected-mode overdub \
  --output /path/to/a-new-audit.json
```

`--expected-mode` is the **required output for this evaluation**, not an
inference from the presence of a translated voice or from the job's
`done` status. A regular `replace` dub may intentionally have one audio
stream; in contrast, an Overdub with original and translated audio selectable
must have two independent streams.

Deterministic findings:

- MP4 audio stream count and mismatch against requested replacement/Overdub.
- Original reference clip WAV duration, actual transcript word count, and
  implausibly high words per second. Short samples and misaligned transcripts
  are visible *before* accepting a claim of high-fidelity voice cloning.
- Source cue duration versus the envelope-detected spoken duration of the
  corresponding saved TTS line. This checks a measurable timing violation,
  not the preservation of *every pause inside a sentence*.
- Existing `clipped_lines.json` proves whether source speech was actually
  truncated at a neighboring cue or at the video boundary.
- The **raw** best CAM++ scorer similarity per line, not a calibrated voice
  match probability or a proof of quality. No arbitrary pass/fail on this
  model score without an independent reference benchmark.

The report always retains a list of perceptual properties requiring
independent review: Russian accent, voice likeness, internal pauses, and
source/translation level balance. Even an issue-free report is labelled
`not_perceptually_verified`, never a definitive audio-quality PASS.

## First observed result: 2026-10-31, 234.7-second vocal lesson

A read-only run over the finished **Breath Control for TOTAL Beginners**
project (job ID `a45f8233`) produced:

- Actual output: **1 AAC audio stream**, with declared `replace` mode;
  required for this user test: **Overdub with original and translation**.
- Speaker `SPK1`: **0.9 seconds** of reference audio with an 18-word English
  prompt (20 words/sec). Only one translated segment was assigned to this
  speaker; it is a very unreliable reference, not evidence of a true second
  speaker.
- **5 speech segments** longer than their allocated source cue by more than
  0.20 seconds, with **3.14 seconds** of combined excess.
- **1 final clipped line**, missing **1.461 seconds** of its speech.
- For that very short second-speaker segment (source line 20, zero-based
  scorer index 19), the highest of its four raw similarity model scores was
  **0.3106**. This number is a model output, not a calibrated probability.

The older renderer already guards against *overlapping playback*, but simply
truncating speech to the next cue can discard words and does not preserve
original intra-line breathing and pauses. These are different acceptance
criteria. Likewise, producing a stereo mix does not imply the original audio
is independently selectable or audible.

This first report is not a fix for pronunciation, diarization, translation
quality or adaptive ducking. It establishes reproducible **pre-acceptance
evidence**. Next work is to expose the audit in the project UI, validate
source-language accent by independent native-language listening, and evaluate
multi-span pacing, source music preservation and alternate reference selection
on the same media. Do not automatically map a 0.9-second speaker to another
voice without ground truth confirming identity.
