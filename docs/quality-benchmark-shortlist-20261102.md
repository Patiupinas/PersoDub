# PersoDub P1-B: independently sourced quality benchmark shortlist

**Verified:** 2026-11-02; active development branch based on draft PR #42. **Scope:** EN/DE/ES lessons -> Russian speech with preserved original exercises, pauses, instructor identity and original bed. This is not a TTS model selection by one proxy score.

## What matters (smallest useful test suite)

| Priority | Dataset / reference | Stage and independent oracle | Status / exact limitation |
| --- | --- | --- | --- |
| P0 | [CV3-Eval](https://github.com/QwenAudio/CV3-Eval), multilingual and cross-lingual zero-shot | RU target text, held-out source voice; Russian ASR WER/CER, speaker embedding SIM and signal quality (DNSMOS) | **NOT_RUN** on CV3. Official repo provides scoring code; Hugging Face Open TTS Leaderboard has a Russian subset. Original clip/source rights vary. None of WER, SIM and DNSMOS alone measures Russian native accent. |
| P0 | [FLEURS](https://huggingface.co/datasets/google/fleurs) (CC BY 4.0) | EN/DE/ES/RU source ASR against *dataset transcripts*, not model self-transcriptions | **OBSERVED: real cached RU test pilot below**. Other languages NOT_RUN. Read speech, no source singing boundary truth. |
| P0 | [FLORES+](https://huggingface.co/datasets/openlanguagedata/flores_plus), maintained replacement for archived FLORES-200 | EN/DE/ES -> RU human parallel sentences keyed by `split+id`; chrF++ reference metric and optional XCOMET / MetricX after checking human challenges | **NOT_RUN**. Evaluation-only CC BY-SA 4.0; official HF repository is gated for terms acceptance. Dev for threshold tuning, devtest held out. Do not train/tune on test rows. |
| P0 | [GTSinger](https://huggingface.co/datasets/GTSinger/GTSinger) | Paired speech/singing and singing-technique labels, phoneme/pitch support for EN/DE/ES/RU | **NOT_RUN** on this branch. Dataset terms must be accepted. Positive protected-vocal clips alone cannot establish continuous speech-to-exercise A4 boundaries. |
| P0 | **Owner's 234.684s original lesson** with human-reviewed A4 | True 48 kHz source-time speech/exercise boundaries, exact preserved-original PCM, pauses, full bilingual adequacy | **NOT_RUN human A4 gold**. Existing 34s research mix and dual-track exports are not independent singing-protection acceptance. |
| P0 | Existing six-pair offline [blind voice-review pack](p1-voice-reference-blind-review-20261101.md) | 3+ independently identified Russian-native raters: accent MOS, voice likeness, natural pauses, source-bed audibility separately | **NOT_RUN** genuine human ratings. Private 6-pair A/B audio and evaluation UI are ready on Mac. |
| P1 | [MuST-C](https://aclanthology.org/N19-1202/) EN->RU TED talks | Speech->Russian text on segmented talks with professional translations; use talk-disjoint split | **NOT_RUN**, secondary spoken-lecture domain beyond web text. Not a DE/ES->RU or vocal-coaching gold set. |
| P1 | [VocalSound](https://github.com/YuanGongND/vocalsound) (CC BY-SA 4.0) | Independent cough/laugh/cry/scream/sneeze/throat-clear *clip labels* | **NOT_RUN**, no automatic full-corpus download. Does not include singing and is not continuous-source A4 boundary gold. |
| P1 | [RAVDESS](https://zenodo.org/records/1188976) (CC BY-NC-SA 4.0) | Audio-only actor-disjoint English speech vs song and emotion clip labels | **NOT_RUN** here; actor IDs must not appear in both development and held-out. No in-clip exercise transition truth. |
| P2 | [RUSLAN](https://ruslan-corpus.github.io/) | Russian natural-speech text/audio pronunciation anchor | **NOT_RUN**, single speaker; not proof of cross-language cloned identity. |

**Direction check:** CoVoST2 offers RU->EN and EN->DE but *not EN->RU*, so it is not an EN->RU quality reference. FLORES+ is parallel **text**, not a spoken-song benchmark. Audio from RAVDESS / VocalSound / GTSinger is labeled per clip or phonation and does not automatically authorize any A4 translate/preserve action. Benchmark code licences and audio collection terms are distinct.

**Automatic metrics vs actual product quality:**

- ASR: WER/CER against **dataset transcripts**; inspect *word errors* and cross-model disagreement. Transcript alignment uses a separate human source clock when available.
- Translation: reference chrF++ plus an independent bilingual adequacy/MQM review of meanings, numbers, vocal terminology and distant paraphrases; model-only MiniLM, NLI, COMET/QE are **OBSERVED** and must be validated against held-out human judgements. WMT24 found XCOMET and MetricX-24 strong on MT quality, but benchmark-level leaderboard results are not per-phrase gold.
- Voice: matched source text, seed, speaker ref and candidate duration for CV3-based WER/CER/SIM; native-Russian human accent, speaker resemblance and pauses are separate categories and cannot be inferred from speaker embeddings or audio noise metrics.
- Protected vocal exercises: time-weighted false `TRANSLATE` seconds on independently annotated exercise intervals, `PRESERVE` PCM identity outside fades; status `REVIEW` remains a valid stop rather than guessing translation.
- End-to-end: compare exact original video SHA, independent two-stream audio topology, source-only selectable original, reproduced Russian-text timings, source bed audibility, no clipped speech, true 2h/4h/6h resume metrics later.

## Actual offline FLEURS RU benchmark: 2026-11-02

The Mac already contained **60 locally cached** Google FLEURS **ru_ru test** recordings and associated original professional transcripts under the separate WhisperNotes corpus (not a runtime dependency). No new data or weights were downloaded. An eight-utterance SHA-frozen subset was deterministically selected using `persodub-fleurs-test-v1`. The local original FLEURS corpus files were used read-only.

The added minimal runner `benchmarks.persodub.fleurs_eval` reuses `benchmarks.persodub.metrics.asr_metrics`, validates the independent reference provenance, audio path, clip metadata/duration, rejects duplicates and path escapes, computes WER/CER against *original* `rawText`, records SHA of each external WAV and the exact local model bin. One test selection can be replayed with a different ASR candidate without tuning to its results.

- Model: cached Faster-Whisper Large-v3 / CTranslate2 CPU int8, Mac ARM64.
- Model weight `model.bin` SHA-256: `69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1`.
- Exactly **8 / 60** cached test recordings, **142 reference words**, **876 reference characters**.
- **WER = 5/142 = 0.035211 = 3.5211%**; **CER = 5/876 = 0.005708 = 0.5708%**.
- Exact selected FLEURS IDs: `1694,1737,1693,1813,1920,1752,1974,1824` with prefix `fleurs_ru_`.
- **Status OBSERVED**, no calibrated product pass/fail threshold, no native accent / speaker identity verification, and only 8 test items, not a FLEURS-language leaderboard score.

Local private report on Mac: `~/Documents/PersoDub-Research/reports/p1-quality-benchmarks-20261102/fleurs-ru-whisper-largev3.json`. This includes source transcripts and per-utterance decoded text, so it is **not committed to Git**.

Reproduce on Mac (existing cached sample and model only):

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-quality-benchmarks-20261102
~/.persodub-dev-kit/engines_venv/bin/python -m benchmarks.persodub.fleurs_eval \
  --root "$HOME/Documents/whispernotes" \
  --manifest "$HOME/Documents/whispernotes/Sandbox/BenchmarkCorpus/ru-corpus/fleurs-ru-eval.json" \
  --language ru --limit 8 \
  --model-dir "$HOME/.persodub-dev-kit/models/whisper/faster-whisper-large-v3" \
  --out "$HOME/Documents/PersoDub-Research/reports/p1-quality-benchmarks-20261102/replay-fleurs-ru.json"
```

## Workflow and next one action

The **current bottleneck is independent quality truth**, not adding another synthesized model. Use existing stages, not a second quality engine. First, use the already prepared native-Russian six-pair voice panel on Mac **and manually approve 15-30-second A4 mixed speech/exercise boundaries of the 234s source**; those real human anchors are prerequisites to product-level native accent and vocal-preservation PASS. In parallel, select up to 8 genuine CV3-Eval Russian voice-cloning samples *without downloading the whole corpus*, then run identical Qwen `timbre` and `ICL` on frozen target text and reference voices to obtain repeatable objective WER/CER/SIM before any new provider choice.

## Authoritative external references

- FLEURS: https://huggingface.co/datasets/google/fleurs
- Official CV3-Eval implementation and metrics: https://github.com/QwenAudio/CV3-Eval ; HF multilingual TTS benchmark: https://github.com/huggingface/open-tts-leaderboard
- FLORES+ active dataset and access conditions: https://huggingface.co/datasets/openlanguagedata/flores_plus
- GTSinger: https://huggingface.co/datasets/GTSinger/GTSinger
- VocalSound: https://github.com/YuanGongND/vocalsound
- RAVDESS: https://zenodo.org/records/1188976
- MuST-C: https://aclanthology.org/N19-1202/
- WMT24 Metrics Shared Task: https://www2.statmt.org/wmt24/pdf/2024.wmt-1.2.pdf
