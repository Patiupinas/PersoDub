# A3-1: source-clock speaker turn grouping (no inference)

This independent module is a narrow, **non-operational** port of the deterministic `SessionPhraseBuilder.swift` logic in [Patiupinas/whispernotes](https://github.com/Patiupinas/whispernotes) pinned at `2f863db64f41680365a0f9f8772f9147034ea675`; the source file SHA is `73c369b396d9eac1a02a69c611009b4b7bd8e4cf`. The original Swift regression fixture is `SessionPipelineV2Tests.phraseBuilderMergesSameSpeakerTurns`.

Existing PersoDub `app/text/srt.py:merge_by_pause()` merges **transcribed and translated subtitle cues** with sentence/slot budgets. This new module instead groups **diarization speaker turns** as observational evidence, which is a distinct responsibility. It does not touch ASR models, WhisperNotes runtime, subtitles, or the main pipeline.

## Contract

`app.vocal_phrase_groups.build_phrase_groups(turns, *, sample_rate, merge_gap_samples=None, max_phrase_samples=None)` takes `SpeakerTurn(start_sample,end_sample,speaker_id,source)`. All boundaries are integer samples on the already-decoded source PCM clock. Default same-speaker gap is 10 seconds; maximum group duration is 45 seconds, mirroring the WhisperNotes reference. Both can be overridden as exact sample counts. Output contains `PhraseGroup(phrase_id,speaker_id,start_sample,end_sample)` with deterministic `phrase_###` IDs and `_N` suffixes for splits. Unknown speaker is retained as an explicit label. Fallback and invalid zero/reversed spans are excluded as in the reference; uncovered timeline remains subject to separate A4 REVIEW handling.

The original Swift `turnCount` is set to 1 for every emitted phrase, including merged turns. This port intentionally **does not expose** that misleading field. Source confidence and reasons remain attached to the original diarization observations and are not aggregated into a fabricated confidence.

## Vocal lecture difference

A 10-second phrase grouping gap may include a sung demonstration or vocal effects. This module can therefore produce a phrase spanning an unobserved protected interval, as explicitly demonstrated by a regression test. **A3 output is never translation permission.** A2 acoustic protection, A4 sample-level decisions and validated PCM preservation remain the authority. A0 must not blindly use a phrase as one TTS segment. The default 10-second threshold is an upstream characterization, **not a calibrated setting for vocal lectures**.

No user data, external models or dependencies are required for the unit tests. Run `python -m pytest tests/test_vocal_phrase_groups.py -q`. Cross-platform CI will be the next independent check after the PR is published. Existing PersoDub main stays unchanged.
