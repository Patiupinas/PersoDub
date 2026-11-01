# P1-B voice reference and native-Russian A/B listening

**Research date:** 2026-11-01, Mac M1 Max, local Qwen3-TTS 1.7B on Apple MPS and Faster-Whisper Large-v3 on CPU int8. **Parent:** Draft PR #41 (source-bound Whisper STT). This update adds a usable, offline blinded-review instrument to the existing benchmark. The source job, its English and Russian subtitles, original media, original voices, `main`, and A4 approved action data remain untouched.

## Real sample and why it matters

Frozen completed original lesson: *Breath Control for TOTAL Beginners*, **234.684 seconds**, source MP4 SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`.

- Existing SPK0 voice reference: `74.78-81.68s`, **6.900s**, extracted from the local Demucs vocal stem. Existing persisted `speaker_refs.json` has a reference script explicitly discussing vocal *trills*. That is a possible phonation/intonation confound, **not proof** that singing actually occurs in the whole reference.
- Existing SPK1 reference: only **1.08s** with an impossible 18-English-word reference script inherited from the damaged source ASR. This is a known real-job quality failure; no arbitrary speaker merge or retroactive rewrite was performed.
- New experimental SPK0 speech-dominant reference: `158.780-165.340s`, **6.560s**, cut as mono PCM24k from the same existing `vocals.wav`, SHA-256 `44e7f18398d0f4e03702d5f40ea3ff589a971a89e2d2d0257b531489530a0e95`. This span is within the earlier source AST observations whose leading label was speech, but it has **no independent approved A4 speech/singing boundaries**. A separate local Whisper Large-v3 decode gave: *Your lower abdomen should move in towards your spine. Belly button moves in towards the spine and up towards the ceiling.* This script is model-transcribed, not human-certified.

Two controlled comparisons use three identical, frozen Russian target phrases (prior candidate b/c/d on the 145-179s real source interval):

1. Old SPK0 reference + Qwen `timbre` **vs.** new speech-dominant SPK0 reference + Qwen `timbre`. This isolates the input-reference change.
2. New SPK0 reference + Qwen `timbre` **vs.** the exact same reference + `ICL` with its source reference transcript. This isolates voice-conditioning mode.

Each pair uses the same target text and random seed. The 3 target texts are **model-authored corrected-Russian research candidates**, not bilingual human-approved translations. The reference's human voice identity and source acoustic quality are not certified by an independent same-speaker label.

## Actual Qwen and independent ASR results

| Configuration | Russian ASR word errors | Source-timeline slot overruns | Generated duration, 3 lines |
| --- | ---: | ---: | ---: |
| Old reference, timbre | 1/25 | 0/3 | 12.32s |
| New reference, timbre | **0/25** | **1/3** | 14.72s |
| New reference, ICL | 1/25 | 0/3 | 12.96s |

The new/timbre version of the **3.24-second** short slot generated **3.44 seconds**, whereas new/ICL generated **2.08 seconds**. The old/timbre line fit at **3.12 seconds** but independent ASR heard an added `Но` that the target text did not contain. New/ICL's longer first phrase had one ASR substitution (`Так вы` heard as `так и`). None of these observations establishes native Russian accent, true vocal identity, natural intonation or semantic correctness. **There is no selected winning configuration.**

The isolated Qwen server used loopback port 38999 and was explicitly stopped after the six generated clips. No production jobs were started or changed. Original media, model checkpoints and all private WAVs are excluded from Git.

## Usable offline blinded listening

The existing `benchmarks.persodub.blind_review` now generates an **offline** `index.html` with local A/B/source audio players, side-by-side 1-5 scales for native Russian accent, speaker likeness and pauses, preference A/B/tie, rater ID, self-reported native-Russian checkbox, notes and a local **Download CSV** action. It still generates the CSV template. The answer key is stored **outside** the pack with mode 0600. No third-party requests or tracking.

For **voice-only** dry clips, pass `"rating_profile": "voice"` in the pair manifest. Original-bed audibility is correctly marked `N/A`, rather than asking raters to score an original bed which is not present. For genuine Overdub samples, omit this option or use `"rating_profile": "overdub"`; original-bed audibility remains a required 1-5 dimension.

The new `benchmarks.persodub.blind_review_score` validates actual, independently exported CSVs, unmasks labels using the private key, computes paired group-specific MOS and preferences, and reports `NOT_RUN` before ratings or `INCOMPLETE_REVIEW_PANEL` with fewer than three self-reported native-Russian raters. At three it reports `OBSERVED_HUMAN_RATINGS`, **never an automatic release PASS**. Self-report is not independent identity verification, and three clips from one source speaker do not justify claims about broader speakers, languages, or confidence intervals.

### Private real Mac evaluation assets

All paths below are under `~/Documents/PersoDub-Research/reports/p1-voice-reference-ab-20261101/` and never committed:

- `blind-voice-pack-v2/index.html` - open in Chrome on the Mac; **six blinded pairs** with original voice samples and a full offline rating form
- `blind-voice-pack-v2.zip` - verified portable offline package of 18 WAVs (six original source / 12 A-B), `index.html` and `ratings_template.csv`, without the private mapping or media/model weights beyond the selected clips; **8,723,127 bytes**
- `private-assignments-v2.json` - deliberately outside the shareable A/B pack, never give it to blind raters
- `pairs-private-v2.json` - input manifest with direct audio paths and unblinded comparison groups
- `source-reference-asr.json`, `voice-ab-manifest.json`, `qwen-voice-ab-independent-asr.json` - exact real inference and test results
- `reviewer-status.json` - **NOT_RUN**, no actual native-Russian reviews yet
- `browser-smoke-private/` - **synthetic** test ratings only, not an actual reviewer or valid quality result
- `run_voice_ab.py`, `score_voice_ab.py`, `verify_browser.cjs` - local experiment scripts
- Audio WAVs and screenshots remain private; no bulk datasets downloaded

To score subsequently exported human CSV files, from this branch:

```sh
python -m benchmarks.persodub.blind_review_score \
  --private-key "$HOME/Documents/PersoDub-Research/reports/p1-voice-reference-ab-20261101/private-assignments-v2.json" \
  --ratings /path/rater1.csv /path/rater2.csv /path/rater3.csv \
  --out /private/path/human-voice-result.json
```

## Current verification / next owner action

The browser E2E test on macOS Chrome loaded all **6 original** and **12 blinded A/B** audio players, rejected missing rater ID and incomplete ratings, downloaded CSV for six pairs and made **zero external network requests**. Synthetic one-rater scoring reported **INCOMPLETE_REVIEW_PANEL**; the real/no-rater report remains **NOT_RUN**. Focused regressions check HTML escaping, A/B hiding, key isolation, N/A dimensions, duplicate raters, missing/invalid ratings, non-native ratings exclusion from accent MOS and comparison orientation. Final exact-branch Mac verification: **2,698 Python passed, 5 skipped**; **1,146 UI Node passed**; **713 Desktop Node passed**. Ruff app/benchmarks/tests, Python compileall, UI inline check, English/Korean JSON and `git diff --check`: **PASS**. Browser E2E opened all 18 real local WAVs, downloaded CSV and made zero external requests. Headless Chrome used existing local browser installation; neither software packages nor model weights were downloaded.

**Next action:** collect and inspect **three genuinely independent native-Russian listener ratings** on these six A/B pairs (and on the source/original reference), then select only the candidates that meet accent/identity/timing criteria. In parallel a human must review the A4 event boundaries for the full lesson before making a protected-vocal Overdub. **Do not use the synthetic browser-smoke CSV as human quality evidence.**
