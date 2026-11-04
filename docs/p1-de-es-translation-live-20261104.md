# P1-K: German and Spanish to Russian translation on real vocal instruction audio

Date: 2026-11-04. Experimental branch: `feature/p1-de-es-translation-20261104`, stacked on Draft PR #53. This change is limited to the existing Antigravity translation provider, deterministic text gate, and tests. No merge to `main`.

## Actual YouTube inputs

- German: Dirk Hoppe, "3 Min. Vocal Tipp: Richtig atmen beim Singen", https://www.youtube.com/watch?v=qXFb5h4cYWc (source video ~144 seconds).
- Spanish: unComo, "EJERCICIOS de RESPIRACIÓN para CANTAR", https://www.youtube.com/watch?v=_CjGC5lwQuU (source video ~229 seconds).
- Real source audio was obtained on the authorized Mac for private research, and each source was decoded to a separate first-80-second 16 kHz mono WAV.
- Cached pinned `faster-whisper-large-v3`, CPU int8, explicit `de` and `es` language modes decoded the source. The source text is an ASR hypothesis, not a hand-approved transcript.

## Verified translation experiment

- Real Antigravity CLI 1.3.5 translated the first 8 ASR cues in each language using four-cue batches. German: 19.13 s; Spanish: 22.01 s.
- Before gate correction the same candidates flagged 5/8 German and 3/8 Spanish cues. With source-sentence continuation support and one-word source-clock slack: 1/8 German and 0/8 Spanish flagged. The remaining German cue 6 has more words than can comfortably fit a 3.42-second source window.
- The German trial preserved the distinctions `Bauchatmung`, `Brustatmung`, and `Zwerchfellatmung` as Russian abdominal, chest, and diaphragm breathing. The Spanish trial preserved `respiración clavicular` and the explanation of controllable breathing. These are direct source/candidate comparisons, **not** an independently bilingual-scored semantic PASS.
- A real German source cue ending with a comma was previously rejected solely because the Russian translation also ended with a comma; spoken lecture sentences cross source ASR cue boundaries. Short greetings also triggered an unrealistic words/seconds check.
- Private trial transcripts, raw RU candidates, source audio, QA JSON, and execution scripts: `~/Documents/PersoDub-Research/reports/p1-de-es-translation-20261104/`. No media or full source scripts are committed.

## Product changes

- The existing Antigravity provider now requires an explicit known source language: English, German or Spanish, using supported name/code aliases. The prompt uses a neutral `source` field rather than silently treating every source as English, and explicitly preserves vocal training terminology and original-source cue order.
- In the Antigravity-only quality gate, source cues that clearly end mid-sentence can have Russian continuation fragments without false `possible_sentence_fragment` rejection. A completed source sentence still needs completed Russian wording.
- A short cue gets one additional Russian-word tolerance in the source-clock length review, preserving a bounded check for genuinely too-long cues. The default gate behavior used by other callers remains unchanged.
- These checks are structural/pacing tests. An unflagged translation does not prove faithful meaning, native Russian prosody, or A4 singing boundaries.

## Remaining

- The source video/audio is private, and no user-authorized A4 vocal exercise ground truth has been established for these two YouTube clips.
- Natural-speech Russian TTS, two-audio-track MP4, and multilingual mixed-speech/musical protection remain separate downstream acceptance tests.
- The unverified source ASR and translated meaning require independent bilingual evaluation before treating this as a fully accepted dub.

## Extended first-80-second research result

The complete first-80-second ASR transcript (not only the initial eight cues) was submitted to the same CLI adapter for Russian candidate generation:

| Source | ASR cues | CLI elapsed | Old gate flags | Revised gate flags |
| --- | ---: | ---: | ---: | ---: |
| German | 22 | 69.74 s | 16 | 2 |
| Spanish | 12 | 34.82 s | 4 | 2 |

These are source-clock structural flags only. German remaining flagged cues 6 and 8 and Spanish cues 2 and 4 require Russian text shortening or manual review before production synthesis. The full 80-second comparisons and the original audio are reviewable together in the Mac-local `compare-de-es.html`, with matching `de_candidate_ru.srt` and `es_candidate_ru.srt`. Neither complete translation is semantic gold. Machine testing the gate against the immutable raw candidate texts did not produce audio or an A4-approved video.

Focused verification on this branch using Mac conda Python 3.12 with isolated `num2words` test dependency: **45 passed, 1 deselected** (`tests/test_antigravity_cli.py` and `tests/test_vocal_overdub.py`); the deselected API test requires the canonical FastAPI/Starlette environment because this independent conda installation has mismatched package versions. Ruff, Python compileall, and git whitespace checks passed. No fresh full project regression has been claimed.
