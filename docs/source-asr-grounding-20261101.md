# PersoDub P1-B: source-ASR grounding before automatic translation QA

**Date:** 2026-11-01, Europe/Madrid. **Host:** Raymonds-Laptop.local (Apple M1 Max). **Stack parent:** Draft PR #37, `feature/vocal-translation-contrastive-20261101`, GitHub SHA `76d225e9124dd833c4113566da7163c7a87f679f`. **Implementation branch:** `feature/vocal-source-asr-crosscheck-20261101`.

## Finding from actual source audio and job data

Real job `a45f8233` (*Breath Control for TOTAL Beginners*, 234.684s), frozen input video SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`. The 8 private EN/RU review spans were selected by the previous measured MiniLM, NLI and COMET-QE benchmark. The **original** job reports `stt_engine=whisper`; current PersoDub worker defaults to a local `faster-whisper-large-v3` model, but the completed job does not identify the exact original model checkpoint SHA, so that identity is **not independently attested**.

Independent *decodes*, not independent model architectures, were performed **directly on original `input.mp4` PCM**, with 1.8 seconds of context at each edge. Both OpenAI-Whisper checkpoints were already cached locally; no additional model downloads were needed for this investigation:

- `base.pt` SHA-256 `ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e`
- `small.pt` SHA-256 `9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794`

The prior transcript `transcript.json` contains **41 source cues / 731 word timestamps**; **106** recorded words have start and end timestamps identical. The application source-timing auditor flagged **12 of 41** cues for collapsed durations, implausible spoken word rate, or words outside their parent cue. **These are 12 source-timing review items, not 12 mistranslations.** Example source cue `145.64-146.72s`: **16 of 18 words** have zero duration, with 16.667 words per second. Both separate Whisper checkpoint decodes instead recognize a short clause about working through a song; the previous source text talks about retrieving muscles. The source timeline/text is therefore unreliable as a semantic translation oracle.

The second difficult interval `171.72-181.20s` includes possible sustained /brrr/ vocalization in Whisper Small, while Whisper Base produces part of an explanation. This suggests the interval may mix a vocal demonstration and speech; **A4 remains the only translate/preserve authority**, so no automatic preserve action is taken.

A third interval `116.06-125.24s` illustrates why two ASR models are not a quality vote: Whisper Base loops on the unrelated repeated phrase `your abs`, whereas Whisper Small corroborates much of the original English transcription. This is classified as **ASR probe disagreement**, not necessarily a source-audio or translation error.

## Grounded eight-interval triage

| Source seconds | Whisper Small ordered lexical coverage | Whisper Base coverage | Next diagnostic route |
| --- | ---: | ---: | --- |
| 9.08-17.76 | 1.000 | 0.667 | Translation adequacy with source audio |
| 36.18-40.20 | 1.000 | 1.000 | Translation adequacy with source audio |
| 74.78-81.68 | 1.000 | 0.889 | Translation adequacy with source audio |
| 116.06-125.24 | 0.906 | 0.031 | ASR probe disagreement / decoder loop |
| 130.94-131.82 | 1.000 | 1.000 | Translation adequacy; likely legitimate paraphrase despite low embedding score |
| 145.64-146.72 | 0.000 | 0.056 | **Recheck original transcript and timing first** |
| 171.72-181.20 | 0.037 | 0.463 | **Review vocal demonstration/speech boundaries** |
| 188.90-194.84 | 1.000 | 0.714 | Translation adequacy with source audio |

**Read this table correctly:** ordered lexical coverage is not WER, phonetic confidence, word accuracy, or an adequacy score. The decodes have intentionally padded context. A low score is a review flag, not a definitive transcription error. The models belong to the same Whisper architecture family; neither run has been verified against independently heard and corrected human audio labels. No bilingual adequacy PASS is claimed.

Five spans can proceed to bilingual translation evaluation with audio context; one needs original timeline review, one needs possible vocal-event boundary review, and one exposes a fallible independent ASR probe. The previous `0.66` MiniLM similarity must **not** be interpreted as 66% translation accuracy. Existing EXPLICIT cardinal/music-key fact hints and three translation models remain diagnostic only.

## Code changes

- `app/source_transcript_quality.py`: small, bounded, deterministic source-transcript integrity analyzer. Inspect `transcript.json` word times, zero-duration counts, out-of-cue timestamps and high per-cue words/second, without reading/copying audio.
- `app/dub_quality_audit.py`: an additive read-only `source_transcript_timing` result and `source_transcript_timing_review` issue on finished jobs. Missing word timestamps return `not_measured` rather than fake PASS. No auto-retranslation or user file mutation.
- `ui/src/qualityReport.mjs` and en/ko translations: display source-timing quality issue distinctly from generated-speech timing and clip issues.
- `benchmarks/persodub/source_asr_crosscheck.py`: read-only local source MP4 interval decoding and independent Whisper `base`/`small` cross-check. It demands an explicit, existing checkpoint file, never triggers implicit downloads, never saves extracted WAV media, and reports exact file/checkpoint SHA-256.
- `benchmarks/persodub/source_asr_evidence.py`: merges both independently decoded ASR reports with existing original word timestamps, rejects stale media/review/interval identities, separates single-model decoder loops from possible sustained vocalization, and emits a private human review CSV with **blank** annotation columns.

These changes do not alter live server processes, the installed application, A4 routing, source recordings, translated subtitles, trained models, output audio or the production `main` branch.

## Local, private artifacts

All reports contain the user's source lesson text and remain **off Git**:

`~/Documents/PersoDub-Research/reports/p1-asr-validation-20261101/`

- `whisper-base-source-crosscheck.json`
- `whisper-small-source-crosscheck.json`
- `source_asr_evidence.json` (input-hash-bound source-first 8-span triage)
- `review_pack_audio_grounded.csv` (8 EN/RU pairs, both fresh decodes, issue route, human-review fields empty)
- `full-python.log`, `ui-tests.log`, `desktop-tests.log`, and local validation output. Verified on this exact source branch: **2,643 Python passed / 5 skipped**, **1,144 Node UI passed**, **713 Node desktop passed**, Ruff + compileall + localized JSON checks PASS. All outcomes are source-test status, not proof of translation adequacy.

Run the source-ASR integrity scan on a finished job, without any ASR inference:

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-independent-asr-20261101
~/Documents/PersoDub-Research/venvs/p0-overdub-20261101/bin/python \
  -m app.dub_quality_audit \
  --work-dir ~/Documents/PersoDub-Research/demos/p0-quality-ui-20261101/workspace/2026-10-31/"Breath Control for TOTAL Beginners_ru"
```

Run local Whisper Small or Base only with the explicitly already cached `~/.cache/whisper/small.pt` or `~/.cache/whisper/base.pt` and the original source media, using `benchmarks.persodub.source_asr_crosscheck`. Build the combined report using `benchmarks.persodub.source_asr_evidence` with `--small-report`, `--base-report`, `--original-transcript`, `--out`, and `--review-csv-out`.

## Controlled source-window experiment

A local installed faster-whisper-large-v3 checkpoint (model config SHA-256 `a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9`) was separately run on source `input.mp4` audio extracted in memory from **140.0 through 174.0 seconds**. All settings were held fixed (CPU int8, English, beam 5, previous-text context enabled); only `word_timestamps` was changed. Without word timestamps: 5 segments. With word timestamps: 5 segments, **0 collapsed among 67 word timestamps**. The short-window transcript was more coherent than the previously saved full-job transcript. The local private report is `large_v3_window_probe.json`. This **does not establish why the earlier full-length run collapsed timestamps**; model checkpoint identity for the original job was not recorded, and segmentation/context is also different.

**Full-input experiment status:** A matching local CPU/int8 Large-v3 test was also started on the complete 234.68-second source, with the same configuration and an intended `word_timestamps=False/True` comparison. After more than five minutes of active CPU computation the first pass had not completed, so this standalone research process was explicitly terminated; no full-input results were emitted. Its result is **INCOMPLETE / NOT_MEASURED**, not evidence that long-form decoding reproduces zero-duration timestamps. The controlled 34-second comparison above remains the only finished Large-v3 A/B test. The attempted command is retained locally as `reports/p1-asr-validation-20261101/large_v3_full_probe.py`; do not count it as a completed benchmark.

## Root-cause hypothesis and next action

The collapsing timestamps might originate in the large-v3 word alignment/decoding path or speech/vocal segmentation; the cached source and independently decoded audio demonstrate **symptoms, not a proven internal root cause**. Public upstream Whisper/faster-whisper reports describe timestamp drift and repetition in some model/word-timestamp configurations, but that does not establish the mechanism in this job.

**Next controlled experiment:** compare bounded 30-60-second chunks of the installed Large-v3 source decoder against the frozen original transcript, with explicit per-chunk execution budgets, cached source/model identity and overlap reconciliation. Do not repeat the unbounded full CPU test as a substitute for a completed result. Independently freeze human-reviewed EN source content and A4 vocal-event boundaries before changing translation models or promoting semantic scores into an automatic quality gate.
