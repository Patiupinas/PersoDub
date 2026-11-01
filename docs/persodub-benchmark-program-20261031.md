# PersoDub: staged scientific benchmark program (2026-10-31)

**State:** Benchmark chain v1 implemented and exercised. First completed
PersoDub project measured; end-to-end natural dubbing and multiple-hour media
are **not** yet certified. This is a benchmark program, not a claim of a new
TTS model or improved output. No model, corpus or commercial export is fetched
by the runner.

## 1. Research question and experiment design

Improve automatic EN/DE/ES -> Russian vocal-lesson dubbing while preserving
speaker identity **without transferring foreign phonetics**, original
sentence and intra-sentence pauses, and musical/singing exercises. Original
audio must remain independently selectable and audible in the mixed Overdub
track, with continuous soft attenuation only around authorized translated
speech. A user should not need to notice an obvious problem before QA does.

Avoid collapsing these independent objectives into one "quality" number.
Always report quality **and** time to complete, CPU/GPU/RSS, disk and
recovery work lost. A working MP4 is not quality validation.

Use three orthogonal data classes:

1. **Controlled synthetic fixtures:** exact source signal, isolated TTS,
   source clock and expected gain. Used for deterministic mixing, timing,
   full-length coverage, and MP4 stream tests. These can establish PASS for
   *those specified technical invariants only*.
2. **Externally labelled media:** a dataset or human-signed transcript,
   speaker turn and vocal-exercise boundaries. Used for ASR WER/CER,
   diarization DER/JER, speech/singing F1, separation SI-SDR and timing
   error. An earlier machine's transcript is not independent gold.
3. **Blinded independent listening:** at least 3 native-Russian judges per
   sample, original voice/reference alongside the Russian A/B, randomized
   position, no vendor or model names. Rate Russian accent/naturalness,
   target-voice similarity, pause naturalness and original-bed audibility
   on independent 1-5 scales. Record all raw scores, not only averages.

Select disjoint development and held-out evaluation **speakers/videos** before
tuning. Do not reuse the same speaker's clips in both groups. Keep separate
recordings for broadcast English, spoken German, spoken Spanish and vocal
exercise demonstrations; don't confuse a short narration dataset with a
mixed spoken/sung tutorial. The user's 234.7s video is a **diagnostic
baseline**, not generalization evidence. Keep Russian native-language
listening separate from voice-clone embedding model selection.

### Pre-registered primary questions

| Hypothesis | Paired A/B control | Primary metric | Decision |
| --- | --- | --- | --- |
| Exercise classifier protects singing | current event hints vs alternative | wrongly translated singing seconds + speech F1 | improve F1 without new destroyed singing |
| More/cleaner speaker references help | current 4-7s sample vs new validated reference | native Russian timbre ABX and phoneme MOS | both voice and accent improve or report tradeoff |
| Alternative TTS improves Russian | current Qwen3-TTS Base (4 takes) vs multilingual model | independent RU readback WER/CER + native accent MOS + speaker ABX | quality first; compare GPU RTF second |
| Source pause map helps | current cues vs pause-aware slots | omitted pause seconds, boundary MAE, clipped words | fewer misses with no new clipped words |
| True Overdub preserves source | current replace vs explicitly authorized Overdub | stream count, source gain in synthetic sections, MOS audibility | independently audible and selectable original, protected exercises full volume |
| Recognition rework saves hours | cold CPU Whisper vs warm per-take SQLite checkpoint | wall time, cache hit count, failed-stage recompute time | no transcription/voice-quality regression |
| Chunking supports long videos | single full WAV vs segmented clock pipeline | source clock drift, peak RAM, peak disk, mux track identity | no lost samples, no missing speech, resumable through 2/4/6h |

These are hypotheses. Metric thresholds are not declared product acceptance
until calibrated on development data and frozen before held-out evaluation.

## 2. Evidence chain and authority

```
source media + immutable SHA, duration, original audio tracks
  -> source separation [stem oracle: SI-SDR, bleed, music preservation]
  -> speech / singing / breathing / laughing [human time-labelled actions]
  -> ASR + word timing [independent transcript WER/CER + word boundaries]
  -> diarization [speaker RTTM, DER/JER, false SPK1 splits]
  -> translation [held-out EN->RU references, glossary, human adequacy]
  -> voice reference [duration, transcript/audio correspondence, purity]
  -> Russian TTS [fixed target text, independent RU ASR, accent + voice MOS]
  -> pacing / silence [source pauses, duration, clipped speech]
  -> Overdub mix [source component level, undubbed exercise integrity]
  -> export [two selectable original + translated audio tracks, video continuity]
  -> end-to-end [cold/warm latency, peak memory and disk, interruptions]
  -> BLIND LISTENING [unseen speakers + native Russian panel]
```

Every stage can fail while the next stage still runs. Keep each independent
failure separate. Never promote `OBSERVED`, a source-derived diagnostic, or
`NOT_RUN` to PASS. "PASS_MEASURED_CASES_ONLY" proves only frozen thresholds
on the cases actually present, **never** production quality. Blinded
audio listening can overrule a purely objective score.

### Currently implemented vs future stage evaluations

The machine-readable ledger is `benchmarks/persodub/stage_catalog.json`.

| Stage | Implemented now | Needed before production grading |
| --- | --- | --- |
| Separate stems | streaming centered SI-SDR | labelled isolated stems, music/vocal protection |
| Speech-vocal decisions | time-weighted F1, overtranslated exercise seconds | actual human labelled mixed lecture, false-positives |
| ASR EN/DE/ES/RU | independently sourced WER/CER | manually checked transcripts and word timing oracle |
| Speaker diarization | catalogue and plan only | RTTM DER/JER and single-speaker false splits |
| Translation | no false semantic PASS | reference chrF/COMET + human semantics/glossary |
| Speaker reference | completed-job QA for length and text density | validated same-speaker segments, purity |
| RU TTS | independent RU ASR readback WER/CER | native Russian phonemes, voice ABX, accent MOS |
| Pacing | boundary MAE, missing pauses and overlaps | pause truth *inside* utterances and word truncation |
| Mix | aligned synthetic source-component gain | LUFS/dynamics, multi-stem independent exercise signal |
| Export | actual FFprobe MP4 tracks, output != source, drift | audio content identification, channel order and playback |
| Resume + long media | previous per-take checkpoint tests | interrupted real 2/4/6-hour E2E |
| Subjective | blind A/B pack and 3-native-RU rating ingestion | actual independent listening sessions |

## 3. Available sources - selective use only

**Do not fetch entire corpora.** Source URLs and intended subsets are in the
catalogue, with rights to be reviewed at dataset level. Freeze exact source
file hashes, actor IDs, reference sentence IDs and annotation protocol.
Recommended experiment intake:

- **FLEURS**: select ~10 transcript-audio utterances each for English,
  German, Spanish and Russian. Score ASR per language; **not** speaker
  diarization or vocal exercise timing.
  https://huggingface.co/datasets/google/fleurs
- **FLORES-200**: select ~20 held-out EN/RU parallel sentence pairs for
  textual translation. It is not a speech/voice benchmark.
  https://github.com/facebookresearch/flores
- **CoVoST2**: use only available translation directions, e.g. RU->EN,
  EN->DE. **Not EN->RU**, which CoVoST2 does not provide.
  https://github.com/facebookresearch/covost
- **RAVDESS**: selective short clips of speech versus song and actor ID
  as *clip* truth. Does not supply mixed-lecture within-clip transitions.
  CC BY-NC-SA 4.0; official commercial license separately.
  https://zenodo.org/records/1188976
- **GTSinger**: selective paired singing/speech recordings with alignment
  where availability and exact target-language subsets are verified.
  https://huggingface.co/datasets/GTSinger/GTSinger
- **VoxConverse / AMI**: independent speaker intervals and diarization,
  not accent ratings; use only a few annotated excerpts.
  https://mm.kaist.ac.kr/datasets/voxconverse/
  https://groups.inf.ed.ac.uk/ami/
- **MUSDB18-HQ**: stems for separation only, not validation of Russian
  dialogue or singing exercises. Educational/research usage conditions.
  https://zenodo.org/records/3338373
- **Owner's 234.7s vocal lesson**: already present locally, no copy to Git;
  private diagnostics only, not human gold. Source-derived timing and
  Qwen scores cannot be used to certify themselves.

Existing PersoDub research manifests in the separate A1/A2 worktrees
preserve selected publicly sourced RAVDESS/SMA/VocalWarmup labels. Reuse
their source links and hashes if independent annotation provenance is valid.
Do not treat an AST/SenseVoice/MOSS *prediction* as labelled ground truth.

## 4. Open-source architecture review (actual source files inspected)

Only selected text files were fetched for inspection outside the Git tree.
No full repository clone, model weights, media or unrelated dependencies.
Fetch date **2026-10-31**, inspected paths and SHA-256:

| Project | Exact inspected source / SHA256 prefix | Transferable design idea | Limitation |
| --- | --- | --- | --- |
| VideoLingo (Apache-2.0) | `core/_10_gen_audio.py` `555500313559`; `core/_11_merge_audio.py` `13938ad3cc6f`; `core/_12_dub_to_vid.py` `6f3d9f12c9a1` | FFmpeg `atempo` duration checks, adding explicit inter-utterance silence, separate bed mix | Pydub in-memory concatenation is not a multi-hour memory design; app notes multiple speakers limitation |
| pyVideoTrans (GPL-3.0) | `videotrans/task/taskcfg.py` `9ac545a720fa` | Per-task state, separate stage corrections, multiple ASR/TTS backends | No blind acoustic quality gate provided by task config; GPL code should not be blindly pasted into different-license project |
| WhisperX (BSD-2-Clause) | `whisperx/alignment.py` `df1e565ebe9e` | CTC forced word-level alignment and explicit handling of out-of-range segments | EN/DE/ES/RU aligner coverage and score must be tested; alignment ≠ native speech naturalness |
| Demucs (MIT) | existing PersoDub dependency, public `demucs/separate.py` | same separation baseline | generic song stems don't guarantee speech purity |
| Chatterbox Multilingual (MIT) | public supported-language/model documentation | Russian-capable candidate for independent TTS A/B | no comparative run performed, GPU/hardware parity must be tested |
| F5-TTS (MIT code, CC BY-NC pretrained weights) | public `infer_cli.py` candidate | reference-style and phoneme/prosody experiment | weights separate usage conditions; not installed |

Upstream repositories: https://github.com/Huanshere/VideoLingo,
https://github.com/jianchang512/pyvideotrans,
https://github.com/m-bain/whisperX,
https://github.com/resemble-ai/chatterbox,
https://github.com/SWivid/F5-TTS.

Source SHA prefixes match the real locally fetched files, not unverified
descriptions. The machine-readable catalogue contains the full source links
and a record of proposed comparisons. Do not import code until a real
benchmark proves its component is preferable.

## 5. Proprietary black-box controls (no access to internal code)

Commercial offerings are **measurement baselines**, not proposed
dependencies. Compare only published interfaces and outputs obtained through
authorized accounts. No commercial calls were made in this investigation.
All vendor tests use the same fixed source 15-30s clips and independent
native-Russian panel, blind to the vendor. Keep reference selection, target
text and timing fixed when the API permits, otherwise record confounders.

| Vendor | Published control / potential insight | Suggested paired experiment |
| --- | --- | --- |
| ElevenLabs Dubbing v2 | `Cloning strength` 0-10 trades off timbre vs native target accent; keeps source background | strength 3 vs 7, target native RU accent vs voice ABX |
| Rask AI | segmented speaker assignment and independent voiceover/mixed-background WAV export on eligible plan | same clip: clean voiceover and mixed output to isolate background loss |
| HeyGen Video Translate | dynamic duration and editable translations | compare available timing strategy with explicit untouched pauses |
| Deepdub eTTS | `targetDuration`, `accentControl`, `voiceReference` in published API | one Russian phrase under same target duration, accent parameter changed |
| Captions AI | user-visible multilingual editor, replacement export | UX control, but don't assume a source-selectable Overdub file |
| RWS / Papercup IP | managed/enterprise editorial workflow after acquisition | compare editorial QC concept only, not a runnable model |

Official references:

- https://elevenlabs.io/docs/overview/capabilities/dubbing
- https://www.rask.ai/api/voice-cloning-api
- https://help.heygen.com/en/articles/10029081-how-to-get-started-with-video-translation
- https://github.com/deepdub-ai/deepdub-api
- https://captions.ai/help/guides/multilingual/dub-video
- https://www.rws.com/about/news/2025/rws-acquires-papercups-ip/

Product plans, feature flags and costs can change. Benchmark only features
actually available through a connected or explicitly selected account.

## 6. Run the implemented benchmark without inference

All commands run from the PersoDub repo root.

### Full finished-job diagnosis (already executed against owner's project)

```sh
python -m benchmarks.persodub.local_case \
  --work-dir "/absolute/path/to/workspace/2026-10-31/YourJob" \
  --output-dir /private/tmp/persodub-bench-case \
  --expected-mode overdub

python -m benchmarks.persodub.runner \
  --manifest /private/tmp/persodub-bench-case/manifest.json \
  --out /private/tmp/persodub-bench-report.json
```

`local_case` never copies source media, only writes derived timing JSON and
case references. `--expected-mode` must state the user's real objective:
the app's actual mode is not evidence of intent.

### Fully independent stage fixture

Put separate `reference` and `candidate` files in a local directory.
Supply `oracle_kind=dataset_ground_truth` or `human_gold` only when
the reference really is independent, otherwise use `source_derived_proxy`
or `none`. Example case:

```json
{
  "schema_version": 1,
  "suite_id": "ru-tts-readback-heldout-v1",
  "cases": [{
    "id": "spk-b-utt-017",
    "stage": "tts_readback",
    "oracle_kind": "human_gold",
    "split": "holdout",
    "reference": "approved_target_ru.txt",
    "candidate": "independent_ru_asr.txt",
    "thresholds": {"cer": {"max": 0.08}}
  }]
}
```

The `0.08` value is merely an **illustrative, uncalibrated** experiment
threshold. Calibrate on development clips, freeze beforehand and check
held-out performance by speaker and language; do not treat it as current
product acceptance.

```sh
python -m benchmarks.persodub.runner \
  --manifest /path/to/suite.json --strict --out /new/report.json
```

`--strict` exits nonzero unless every supplied case meets *its own*
supported, actually measured criteria. Missing optional gold is `NOT_RUN`;
untested semantics and proxy timings are `OBSERVED`. Reports never
silently overwrite each other. Each available media input's SHA-256 is
recorded; no source transcript/audio body is printed in the report.

### Randomized blinded A/B

```json
{
  "schema_version": 1,
  "suite_id": "ru-voice-2026-10-31",
  "pairs": [{
    "id": "voice-clip-01",
    "source": "/path/source_25s.wav",
    "baseline": "/path/qwen_baseline_25s.wav",
    "candidate": "/path/alternate_tts_25s.wav",
    "target_text": "Это проверка произношения."
  }]
}
```

```sh
python -m benchmarks.persodub.blind_review \
  --pairs /path/to/pairs.json \
  --review-dir /path/to/new-reviewer-pack \
  --private-key /different/path/private-assignment.json
```

The reviewer pack contains neutrally encoded `A.wav`, `B.wav`,
optional `source.wav`, an **offline `index.html` with local audio playback,
ratings and one-click CSV download**, and the CSV template. The private key is
outside the pack. All clips are at most 45 seconds; no video / long file
is copied. Use `"rating_profile": "voice"` for dry voice-only clips, so
original-bed audibility is explicitly `N/A`. Default `"overdub"` keeps
that 1-5 category for true original-plus-Russian mixes.

To score real completed ratings, run `python -m benchmarks.persodub.blind_review_score
--private-key /private/assignments.json --ratings /path/rater1.csv /path/rater2.csv
/path/rater3.csv --out /private/score.json`. It unmasks only with the private
assignment key, checks all pair IDs and rating fields, groups paired MOS deltas,
and distinguishes `NOT_RUN`, `INCOMPLETE_REVIEW_PANEL` and
`OBSERVED_HUMAN_RATINGS`. Three self-declared native-Russian raters are only
a minimum intake; they are not verified identities, and one real speaker
does not support cross-speaker confidence intervals. An observed score is not
an automatic quality PASS. See `docs/p1-voice-reference-blind-review-20261101.md` for real Mac evidence.

## 7. Baseline actually measured on the owner's video

Full report in the Mac-local file
`/private/tmp/persodub-stage-chain-real-20261031/bench-report.json`.
Input video 234.684s and completed dubbed video 234.633s.
The suite actually returned:

- **FAIL**: the requested Overdub requires two selectable audio streams,
  but the output contains **one** AAC audio stream.
- **FAIL**: finished-job QA detects original-track/mode mismatch, a 0.9s
  second-speaker reference associated with an 18-word English transcript,
  five timing overruns and one 1.461s rendered speech cut.
- **OBSERVED (proxy, NOT certified)**: 32 source-aligned line candidates,
  ending-boundary mean absolute error 1.321875s, 19 sizeable pauses
  shortened by 1.84s in total and one overlapping line pair.
- **NOT_RUN x5**: no independent human event intervals, source ASR gold,
  RU speech readback from a distinct model, source-vs-dub mix stem pair
  or native-Russian listening panel. No missing gold was manufactured.

It is correct that the job reached `done`, but incorrect to claim
acceptable dubbing. The benchmark makes this distinction machine-readable.

## 8. Specific next measured engineering decisions

1. **First:** fix real mode selection and source-duck routing. A source
   background must be audible in speech and fully restored during singing;
   the MP4 must have separately selectable Overdub and Original streams.
   Verify synthetic -16 dB/0 dB source gain before testing real mixtures.
2. **Second:** verify falsely split SPK1 identity against the original:
   one 0.9s speaker sample with 18 prompt words is weak evidence. Fix only
   after independent diarization confirms whether there are really two
   speakers. Speaker reference audit is evidence, not authorization to
   merge labels blindly.
3. **Third:** preserve pause intervals and shorten or rewrite translation
   as needed rather than cutting spoken words. Compare forced aligned
   per-word output with human annotated 15-30s spans, then with whole video.
4. **Fourth:** run Russian native-phoneme TTS tests and A/B Chatterbox
   Multilingual versus Qwen3-TTS on identical fixed input prompts and audio
   samples. Test accent and timbre separately, not only cosine embedding.
5. **Then:** benchmark adaptive retakes and model-specific use on held-out
   data, first time-to-usable-clip, total real-time factor, peak memory/disk,
   and resumed 2/4/6-hour jobs. Keep original singing untouched.

No GitHub Actions are added. Run in explicitly permitted local test
sessions only. Keep all input media, recovered speech, provider outputs,
rater identities and private assignment maps outside source control.
