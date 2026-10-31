# Vocal A2/A3/A4: combine transcript semantics with separated-voice phonation evidence

**Status (2026-10-31):** architectural experiment plus verified source-PCM feature summary, **not** a finished classifier, decision-policy change or release. Working branch stacked on [PR #19](https://github.com/Patiupinas/PersoDub/pull/19) -> [#18](https://github.com/Patiupinas/PersoDub/pull/18). No GitHub Actions are used; tests run locally on Apple Silicon.

## The specific failure this addresses

The same three source-disjoint MAVC100 research clips previously showed:

| Acoustic observation | Labeled speech found | Labeled singing mistakenly called speech |
| --- | ---: | ---: |
| INA SMN | 29.74% | 0% |
| Silero VAD v6.2.2 | 50.45% | 0.61% |
| WebRTC VAD mode 2 | 97.04% | 89.79% |

These are **spoken and sung performance clips with accompaniment**, not human-labeled instructional lessons. A strong speech VAD vote can include singing, and a conservative music veto can reject real spoken explanation over accompaniment. More votes of the same kind cannot answer *whether a person is explaining or demonstrating with their voice*.

Existing [A3 local Whisper cue adapter #17](https://github.com/Patiupinas/PersoDub/pull/17) supplies timed literal ASR words. However **a meaningful lyric can be accurately transcribed**, so readable ASR text is not itself evidence that the person is speaking. Existing [A4 policy #6](https://github.com/Patiupinas/PersoDub/pull/6) accepts two distinct acoustic model IDs and does not verify statistical independence. The two INA SM/SMN variants must **not** count as independent votes, and a text model is not an acoustic vote.

## Proposed evidence owners - reuse existing implementation

1. **A0 (source mapping):** decode the original media once into an authoritative source PCM clock, record its SHA, stream/video PTS offset and clip duration. Every derived observation must project to this unchanged source clock. All protected audio ultimately comes from **the original PCM**, not from separated analysis stems.
2. **A3-ASR:** reuse the existing PersoDub local Whisper worker with source-clock words from [#17](https://github.com/Patiupinas/PersoDub/pull/17). A separate context-aware language model may classify each **utterance plus adjacent utterances** as \`explanation\`, \`spoken_instruction\`, \`sung_lyrics\`, \`vocal_demo_cue\`, \`uncertain\`. Text semantic output is an **observation**, not final ground truth. Commands such as "Now sing an A" are *spoken instruction*, while the following phonation is an independent event.
3. **A2-acoustic:** retain INA SMN for the conservative music/speech baseline and Silero as a separate speech activity detector. Analyse vocals from an existing separator (HTDemucs already cached on the Mac; production PersoDub already has its own separation facilities). Estimate **F0 + voiced probability** via pYIN or a suitable already available pitch estimator on that analysis-only vocal track. Record voiced duration, longest uninterrupted phonation, sustained stable pitch, pitch transitions, and later vibrato/phoneme duration evidence. A missing F0 **does not prove normal speech**: breath exercises, fry, growling and screaming may not yield a stable pitch.
4. **A4 fusion:** extend the **existing policy owner**, do not create a second policy engine. Inputs should become typed *semantic evidence* (text + surrounding context), *vocal-phonation evidence* (A2 F0 metrics and reliability), *independent acoustic labels* (INA/Silero) and *temporal overlap*. Protected vocal evidence overrides ordinary ASR transcription, and disagreement produces \`REVIEW\`. Only validated instructional speech with verified source words, no protected acoustic evidence and independently corroborated speech candidates may become \`TRANSLATE\` after A1/A8 calibration. **Do not enable this policy change from the four test excerpts alone.**
5. **A1/A8:** independently annotate real *vocal-technique teaching videos*, including speech-over-music, sung vowels without lyrics, scales, vibrato, portamento, fry, breath and overlap. Measure protected samples or events incorrectly translated, useful instruction speech coverage, REVIEW share, onset/tail errors and source-PCM identity. Existing MAVC100 research clips are diagnostic, not a full vocal-technique holdout.

### Example context

Spoken cue: "Let's sing the vowel A on one note." A3 marks \`spoken_instruction\`, word boundaries stay literal. The next 1-2 seconds may contain a sustained pitched vowel without readable words; A2 supplies harmonic/voicing evidence for a \`vocal_demo\` event, not a translated sentence. Conversely, the lecturer may shout a word or use vocal fry with no stable F0; this must not be promoted to ordinary speech just because pYIN returns unvoiced frames.

## Concrete small on-Mac pitch experiment

**Data reuse only:** two of the original three MAVC100 clips from #18, no new video downloads. **Original labels** selected the *longest* suitable published speech and singing intervals in each clip, then a center crop of 1.5 to 3 seconds was measured; no thresholds were fitted and no holdout qualification is claimed.

- **Pitch estimator:** [librosa pYIN 0.11.0](https://librosa.org/doc/0.11.0/generated/librosa.pyin.html), mono 16 kHz, 2048-frame window, 320-sample hop, F0 75-800 Hz, 20 thresholds. Initial Numba compilation took ~36 s; cached calls ~0.02-0.05 s for each short interval. Source [librosa documentation](https://librosa.org/doc/dev/auto_tutorials/01-intro/03-f0.html) explicitly states pYIN is designed for prominent monophonic sources, not polyphonic mixes.
- **Vocals separator:** previously **cached** original [HTDemucs](https://huggingface.co/adefossez/HTDemucs) model \`955717e8.safetensors\`, source SHA256 \`d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd\`, loaded **strictly** with Demucs 4.0.1 and Torch 2.6.0. CPU, \`shifts=0\`, selected 4-second excerpts, 4.2-9.7 s per excerpt. The source model was already on the Mac; no additional Demucs weights were downloaded. Derived vocal-stem WAVs exist **only in /tmp** and are not attached to Git.

| Published speech/singing interval | Original mixed-audio voiced fraction | Extracted-vocals voiced fraction | Longest contiguous voiced run (mix -> vocal stem) |
| --- | ---: | ---: | ---: |
| Ellie Goulding, **speech** | 68.42% | 68.42% | 0.50 -> 0.50 s |
| Ellie Goulding, **singing** | 18.63% | **41.18%** | **0.22 -> 0.70 s** |
| Jessie J, **speech** | 36.59% | 56.10% | 0.32 -> 0.32 s |
| Jessie J, **singing** | 79.47% | 79.47% | 0.80 -> 0.80 s |

**Observed:** vocal separation materially changed the available voiced/F0 track in one difficult sung example and preserved the other. But a 0.7s voiced run is **not automatically singing**, and neither four hand-selected intervals nor their soundtrack-mixed ASR transcript can establish sensitivity/specificity for vocal lessons. Confirmed HTDemucs checkpoint loading and source hashes do not establish independently audited separation quality.

## Actual local Whisper word-timestamp evidence (same three videos)

Using **the Mac's already cached OpenAI Whisper Small** checkpoint (483,617,219 bytes, SHA256 \`9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794\`; Whisper package \`20250625\`, CPU) with \`word_timestamps=True\`, \`language="en"\`, \`condition_on_previous_text=False\` and \`temperature=0\`, we transcribed the same three SHA-frozen 30-second clips and projected word timestamps onto MAVC100's published Speech/Singing labels. **No new model weights or media were downloaded** and no lyrics/transcript strings were committed.

| Original performance clip | ASR word intervals total | ASR word intervals overlapping original labeled singing | Positive time overlap with labeled singing |
| --- | ---: | ---: | ---: |
| Ellie Goulding | 49 | 5 | 1.102 s |
| Jessie J | 157 | 21 | 5.942 s |
| Jess Glynne | 77 | 67 | 22.645 s |
| **Total** | **283** | **93** | **29.689 s** |

Each ASR word interval is counted **once per published label category**, even if crossing multiple events of that category. **74** word intervals also overlap speech-labeled events (18.817 seconds). One word can span two distinct categories, so the counts are **not** a mutually exclusive confusion matrix or a word recognition accuracy measure.

A metadata-only report (source SHA, cached checkpoint SHA, per-label word overlap counts, no source lyrics) is frozen in [\`docs/vocal-whisper-pitch-pilot/whisper-word-overlap.json\`](vocal-whisper-pitch-pilot/whisper-word-overlap.json), with local offline snapshot tests.

**Demonstrated failure of text-only gating:** real word intervals coexist with significant gold singing duration. Reading a word transcript cannot prove "ordinary explanatory speech"; a text-semantic model must interpret surrounding instructional context **and** consult independent vocal-phonation evidence. The semantic classifier itself has **not been trained, run or qualified** on true teaching-session gold.

## New pure-data feature boundary

\`app/vocal_pitch_features.py\` adds frozen \`PitchFrame\` and \`PitchSummary\` plus \`summarize_pitch_frames()\`. It consumes **already calculated F0 frames on the authoritative integer PCM clock** and returns:

- sample-weighted voiced fraction
- longest uninterrupted voiced interval, in seconds
- longest run whose F0 stays within a configurable semitone excursion
- average model-provided voiced probability
- duration-weighted median F0 and p10-p90 pitch spread (in semitones)

It rejects missing, overlapping or out-of-range source-clock frame evidence rather than guessing missing audio or ordinary speech. It has **no classification threshold**, no TTS decision output, no ASR runtime, no dependency on Demucs/librosa and no changes to the default PersoDub pipeline. The pYIN adapter is still a local research script; source PCM mapping and pitch-model provenance must be wired by A0 separately. Use the numeric metrics only as candidate evidence until A1/A8 can validate task-relevant thresholds.

## Next bounded experiment

- Reuse the *same three frozen media files* for additional source-PCM tests, but **do not tune a singing decision threshold on these then report its accuracy on these same clips**.
- For **text semantics**, first obtain a real EN/DE instructional lesson with spoken demonstration instructions and vowel exercises (from the open instructional source catalog). Run PersoDub's existing local Whisper per-word cue worker, then compare a context-aware semantic classifier to independently adjudicated events; sung lyrics should remain a separate negative case.
- For **pitch**, freeze a small real vocal-lesson gold with unpitched techniques and clean/accompanied variants; compare pYIN on original mix versus analysis-only vocals. Separate true sustained vowels, melodic sung words, glissandi, expressive speech and instrumental F0.
- Then use the existing \`vocal_align.py\` and \`vocal_policy.py\` A3/A4 stack to integrate only verified evidence **by role**, not by counting identical-family model outputs. Leave \`app/pipeline.py\`, TTS, original PCM and all \`main\` branches untouched.

**Verification policy:** PersoDub repository GitHub Actions are disabled. Acceptance here is local Python 3.11 pytest + pinned Ruff + explicit actual Mac evidence, not a CI badge.
