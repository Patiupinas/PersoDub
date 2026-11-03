# P1 - native-Russian dubbing voices and speaker continuity

**Status:** experimental on branch `feature/p1-ru-voice-diarization-20261103`, stacked on Draft PR #49. November 3, 2026. The user's latest product directive supersedes the prior priority of source-timbre cloning:

1. Primary: **natural, intelligible Russian speech** for long lectures.
2. Provide **several fixed male and female Russian voices** that stay consistent for each source speaker throughout the whole recording.
3. Correct the diarizer's false splits without rewriting the source speaker evidence.
4. **Source timbre / voice cloning is an optional future experiment**, not a release gate.

## WhisperNotes lessons inspected in live source

Read-only examination of the private sibling `~/Documents/whispernotes` code: `Sources/CallRecorderCore/InSessionSpeakerClusterAudit.swift`, `SpeakerDiarizationAligner.swift`, `SessionDiarizationTimelineMarker.swift`, and `SessionPipelineV2Artifacts.swift`. No WhisperNotes code, data, or session audio were changed or copied into PersoDub.

- WhisperNotes uses **0.80** as a speaker-cluster *similarity suggestion* and **0.88** for optional automatic same-speaker merging. Those values are **cosine similarities**, not calibrated “80% same person” probabilities.
- Wrong speaker-boundary splitting used to duplicate individual words in both speakers' lines and bridge two short turns across a third person's speech. Current aligner assigns each word once and respects intervening speaker turns. PersoDub's current CAM++ still estimates one label per existing Whisper subtitle cue, not word-level turns. A future detailed diarization pass must validate word ownership before splitting or joining script cues.
- Compact source audio previously shifted diarization timestamps; WhisperNotes now records the actual full-length source clock and SHA-derived marker. PersoDub retains its exact original source clock and hashes source-cue voice grouping.
- WhisperNotes rejects stale transcript/identity artifacts if diarization changed afterward. PersoDub's new voice-group plan likewise rejects a changed source-clock cue/label stream. It does **not** claim a cross-session voiceprint identity or assign people's names.

## Source speakers vs dubbing voices

`app.speaker_voice_plan.build_voice_plan` takes source-labelled cues and a set of *in-session CAM++ centroid cosine* pair measurements. A pair at **0.80 or above** can share a single Russian **voice group**. A pair under 0.80 remains separate. The design uses complete-link evidence: A≈B and B≈C alone cannot merge all three when A-C is unknown or dissimilar. Explicit `keep_distinct` wins. The plan is source-clock SHA-bound and maps only **`voice_group_id`**, never replaces original `speaker_id`.

`app/scripts/campplus_diarize.py` returns its usual neutral source labels together with optional final-cluster centroid pair cosines. `app/diar_campplus_client.py` builds voice groups; `app/pipeline.py` carries the grouping into subtitle speaker projections. `app/qwen_pipeline.py:_speaker_plan` uses the group for **voice ownership**, while source labels are copied to `source_speaker_id` for evidence and remediation. Five fixed Russian presets are assigned deterministically to voice groups and saved in each job's `russian_voice_assignments.json`; recurrent phrases use the same voice even after long gaps.

This is the requested **dubbing voice de-duplication**, not a rewrite or automatic identification of diarized people. CAM++ model thresholds are different from WhisperNotes's ERes2Net and require project-specific human gold.

## Actual diarization observation

The original 234-second instructional clip has **32 source-language subtitle cues** (video SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`).

- Actual CAM++ **automatic** clustering: **32/32 one source speaker**, no false split on this clip.
- Actual CAM++ **forced to 2 speakers**: **31/32 SPK0 and 1/32 SPK1**; centroid cosine **0.430769**, not 0.80. The 0.80 voice-group rule correctly does not merge such a pair without further evidence. This demonstrates why mere “80% merge” is not a complete diarization correction policy.
- The current local CAM++ worker searches 2-4 clusters and embeds existing ASR cue spans; it is not a full word-level diarization of long overlapping multi-person lectures. No multi-hour or mixed-gender gold validation was performed in this change.

Files are private under `~/Documents/PersoDub-Research/reports/p1-ru-voice-catalog-20261103/real-diarization/`. Do not treat model estimates as human truth.

## New native Russian TTS engine

`app/engines/silero_ru.py` reuses the existing `TTSEngine` protocol, preserving the installed Qwen adapter without changing its original default. It uses **fixed Russian voices**, no imported English recording or clone prompt. The existing sidecar serves a new lazy-loaded `/silero/generate` and `/silero/health` path. It runs one take per text line because the existing best-of-N scorer compares against **source-language** speaker embeddings, which are not an oracle for a native preset voice.

The app already stores a local project's `tts` value, but did not respect it at the pipeline boundary. `app/dub_launch.work_for` now reuses that saved value for local start, restart, retry and revoice. `app/setup.py` and the existing Advanced Options `Text-to-speech` selector offer **Qwen3-TTS** and **Silero RU v5.6**. Qwen remains the default and remains available for other target languages. Silero refuses non-`ru` targets. Resume fingerprints include the selected speech engine and fixed Russian voice bank; Qwen's prior outputs cannot be silently reused for Silero.

The standard model manager now lists **Silero RU v5.6**, a 147,664,410-byte official Russian model at `https://models.silero.ai/models/tts/ru/v5_6_ru.pt`. The vendor URL is pinned to SHA-256 `04cc9b1d08ce38bcaa9d02c488d80d3e6806d17f7eaa7c95982f36a3cbf50b2e` and downloads as a resumable `.part`, with size+hash checks before atomic promotion. The model weights are local-only and **never committed to this repo**.

**Model license:** the official Silero repo lists the community models under CC BY-NC-SA 4.0, with an MIT exception for its separate base CIS TTS models, not the Russian `v5_6_ru`. This is a research-only opt-in integration and not a commercial release or a license grant. See [Silero official README](https://github.com/snakers4/silero-models/blob/master/README.md).

## Real-audio research evidence, same source and same Russian script

All generated media and independent reports are **private on Mac**, under:

`~/Documents/PersoDub-Research/reports/p1-ru-voice-catalog-20261103/`

1. Five fixed voices: `silero-v5-6/index.html`. Equal 24-word Russian lecture fragment; independent cached Whisper Large-v3 CPU int8 heard **0 errors / 24 words for each of 5 voices**, **0/120 total**. This measures lexical intelligibility, **not** native accent/natural prosody.
2. Actual 17-line selective Overdub research: `research-fixed-russian-17-cues/dubbed.mp4`. Native-Russian Silero `aidar`, no source timbre clone; end-to-end real local run **21.45 s**. There were **17 synthetic Russian clips** and 15 original-only cues. Three negligible boundary cuts sum to **0.021s**. This remains **NOT human-certified A4**; no change to original lesson or source experiment.
3. Original source video identity, all 7039 video packets, all 10107 original AAC packets, **123.743s protected original 48kHz PCM**: exact equality in `silero-real-overdub-technical-audit.json`. Two selectable tracks `Original` and `Overdub`.
4. **Matched exact-script machine ASR** (`silero-vs-qwen-exact-ru-script-asr.json`): 17 voice clips, identical source video SHA and translated SRT SHA, same Whisper Large-v3 CPU int8 recognizer. Qwen3 cloned original voice: **15 errors /206 words, 7.2816% WER**. Silero fixed native Russian voice: **7 errors /206 words, 3.3981% WER**. This is a legitimate same-text **lexical metric**, but does not establish native-Russian pronunciation MOS, emotional fidelity, voices matching participants or safe timing across a multi-hour lecture.
5. A **six-pair offline randomized A/B pack** from the actual final mixed audio is at `silero-vs-qwen-six-pair-blind/index.html`, also in `silero-vs-qwen-six-pair-blind.zip`. The separate private A/B answer key is not in the package. All human ratings are currently **NOT_RUN**.

## Validation and next experiment

The code has tests for: source-clock binding, >=0.80 same voice groups, <0.80 distinct voices, no transitive false merges, forced distinct, reappearing speakers after hours, invalid embedding metrics and stale source labels, original source metadata kept, worker's real centroid similarity, fixed RU engine's HTTP implementation, same project voice across reruns, caller-engine cache invalidation, choice and model download UI, and vendor download hash/resume behavior.

**Highest-value next user-facing measurement:** native-Russian listening of the six-pair fixed voice vs source-cloned Qwen Overdub, plus human-labelled multi-person/overlapping-source speech segments for diarization. Use the actual source clock and exact same Russian script. Do not add timbre-cloning models until Russian naturalness is measured.
