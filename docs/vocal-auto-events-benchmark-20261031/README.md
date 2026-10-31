# PersoDub A2: publisher-labelled automatic vocal/event/emotion benchmark

**Executed 2026-10-31 | Research-only | No human event-level gold, no A4 policy change.**

## Goal

Evaluate **automatic speech vs singing vs non-speech human vocal event tagging**, separately from **emotion classification**, using original externally published labels. Avoid judging models against their own output, against Whisper hypotheses, or only by listening to an arbitrarily selected demonstration.

This pilot reuses the **existing Mac AST checkpoint**; it downloads only **24 specifically chosen source WAVs + 8 emotion addendum WAVs**, plus 4 original NUS alignment TXT files, not entire datasets. The audio and all model weights stay on the owner's Mac. This PR contains only URL/SHA metadata, numeric predictions, model identities and tests.

## Original source materials

| Dataset | Preselected audio | Original labels | Limits |
| --- | ---: | --- | --- |
| [ESC-50](https://github.com/karolpiczak/ESC-50) | 10 clips, 2 each for laughing, crying baby, coughing, sneezing, breathing; one from fold 4 and one from fold 5 | Author's original five-second single-class metadata CSV, selected from different Freesound source IDs | Clip-level field-recording classes, not dense onset/offset gold |
| [NUS-48E](https://huggingface.co/datasets/guey-khala-mari/NUS-48E) | 4 audio clips (ADIZ and SAMF, same song 01 spoken and sung) | Published `read` vs `sing`, plus original hand-aligned phone interval TXT SHA for all 4 | The benchmark scores only the read/sing recording label; manual phoneme timing has not yet become source-PCM event gold |
| [VocalSet vocal-quality subset](https://huggingface.co/datasets/zhu3000/squillo-vocal-quality) | 4 clips (F1/M1 scales and passaggio exercises) | Source file subtype `scale` vs `passagio`, both vocal performances | Classifying them as `singing` is **not** recognition of the named technique |
| [RAVDESS](https://smartlaboratory.org/resources/speech-song-database-ravdess/) | 6 baseline acted-speech clips plus 8 predetermined actor 07/08 utterances | Publisher's seven-part recording filenames encode speech channel, actor, emotion | Clip-level acted affect, not spontaneous emotion or precise emotional transitions |

**License:** ESC-50 CC BY-NC 3.0; NUS-48E research-only; original VocalSet CC BY 4.0 (the derivative mirror separately declares MIT); RAVDESS CC BY-NC-SA 4.0. Retain publisher attribution and dataset conditions when reusing the source recordings.

All selected original paths, pinned repository commits, publisher class IDs, source download URLs, audio SHA-256 hashes, and NUS original text annotation SHA-256s are frozen in [selected-source-manifest.json](selected-source-manifest.json). The **original** CSV classification is used for ESC-50, not a guessed label from the filename alone. For RAVDESS the code is decoded according to the publisher's official naming convention.

### Models actually executed locally on Mac M1 Max

| Engine | Exact identity | Category axis | Measured on |
| --- | --- | --- | --- |
| [MIT Audio Spectrogram Transformer (AST)](https://huggingface.co/MIT/ast-finetuned-audioset-12-12-0.447) | Existing local HF snapshot `820128982ca1044325d77662565c4dc77411f709`; weight SHA `d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918` | AudioSet 527 event labels, mapped to 7 primary vocal categories; no prompting | 24 clip midpoints, at most 10 s each, Metal |
| [SenseVoiceSmall GGUF](https://huggingface.co/cstr/sensevoice-small-GGUF) | Q4_K SHA `8a41cfd32e6fd8f5ca330e2425e87bfbed128b42779b40dcc5d100040ec63cc9`, repository revision `e1ad67de9d05137a6a0b02beba1fd66e28df6ae4`; CrispASR 0.8.49 `d9426437` | Audio event tags such as `Speech`, `Sing`, `Cough`, `Breath`; **this runtime deliberately omits emotion output** | Exactly the 24 AST source crops, Metal |
| [SUPERB Wav2Vec2 base ER](https://huggingface.co/superb/wav2vec2-base-superb-er) | Original IEMOCAP four-emotion checkpoint, SHA `dac0f46128deec048751ce33eb1a9caecb570904d3d6cf732d6ec345cd6c2e1b`, pinned revision `441a7599c3b22107314dcbd9166621c5c83f2cc5` | `neutral`, `happy`, `angry`, `sad` **only** | 14 RAVDESS source files, 12 of which have compatible emotion labels; Metal |

The AST runner used torch 2.6.0, Transformers 4.57.3, librosa 0.11.0. For each clip, the middle up to 10 seconds was decoded to **16 kHz mono**; AST's feature extractor pads shorter clips. SenseVoice received the **same actual decoded crop**, not a different random sample. Recorded values are the seven category-group maxima of per-class scores, not calibrated event boundaries or a reliable full probability distribution.

## Real original-label benchmark results

| Source set | AST: top of 7 groups | SenseVoice: matching event tag |
| --- | ---: | ---: |
| ESC-50, 10 independently labelled human-event clips | **8/10** | **4/10** |
| NUS-48E: 2 spoken + 2 sung | **4/4** | **4/4** |
| VocalSet: 4 vocal exercises as coarse `singing` | **4/4** | **0/4** |
| RAVDESS: six selected spoken emotions, coarse speech presence | **6/6** | **6/6** |
| **Total, same 24 audio windows** | **22/24 (91.7%)** | **14/24 (58.3%)** |

The two AST misses in ESC-50 put the publisher's event group at rank **2/7**, rather than #1: one laughter sample was topped by `speech` and one sneeze by `coughing`. SenseVoice failed both selected laughter samples and both crying-baby samples; it correctly identified two coughing and two breathing clips. SenseVoice returned `Sing` on both NUS sung files, but `BGM` (three) or `Event_UNK` (one) on the four VocalSet exercise excerpts.

**Emotion is evaluated separately:** SUPERB (trained for four IEMOCAP emotion classes) scored **7/12 (58.3%)** on publisher-labelled *acted RAVDESS speech*; angry 3/3, sad 2/3, happy 1/3, neutral 1/3. The two baseline `fearful` and `surprised` files were inferred but **excluded from accuracy** because this model has no corresponding output classes. These 12 utterances are too few to establish transfer performance and do not include human annotation of spontaneous emotion. A model trained on RAVDESS itself would not serve as an independently held-out benchmark here.

### A small automatic timeline demonstration

Reused the previously checked 60 s **US Navy Band Vocal Warm-Up** 240p derivative, 16 kHz mono WAV SHA `d409c8994bf9aa05e05e1ba1ec6bfde9e19e000ad33de34224c9136bbc9afc43`, source timestamp offset +60s.

Ran AST on **29 four-second windows, two-second stride**, emitting seven group scores and top three categories for each window, with **absolute original-derivative 16 kHz sample positions**. Example: some windows over the humming passage are still `speech`-dominant while others become `singing`-dominant. A clip-level detector does not magically provide the exact start/end of a vocal demonstration. The timeline is unreviewed model evidence, never sample-level human gold.

## Outcome and integration guidance

1. **Prioritize AST as an additional A2 research audio-event observer** for laughter, crying, cough, sneeze, breaths, speech and singing. It has strong selected-sample group ranking but is **not yet qualified for automatic decisions** or exact event boundaries.
2. Treat SenseVoice as an alternative transcript/event cue with a limited and partly ambiguous event ontology, **not** as a more accurate alternative on this selected event set. Its current CrispASR adapter intentionally does not expose emotion.
3. Keep **emotion as its own experimental observation axis** with its own support mask and score. SUPERB's four-class emotion predictions are independent of the AudioSet activity labels, and should not be substituted for `vocal_demo` or `speech` classes.
4. Keep **vocal technique** separate from both emotion and event: the present 4 VocalSet files demonstrate coarse singing classification only. For vibrato, belt, breathing technique, passaggio, note-level events, evaluate dedicated source annotations (e.g. Annotated-VocalSet or GTSinger) before adding a model.
5. Existing **A1 human review and A4 decision policy remain untouched**. No artificial gold labels, automated dubbing permission, new production model dependency, media binary, model weight, GitHub Action or automatic merge is introduced.

## Reproducing numeric scoring

From a checkout of this PR (Python 3.11+):

```sh
python -m app.vocal_audio_tag_benchmark \
  --sources docs/vocal-auto-events-benchmark-20261031/selected-source-manifest.json \
  --observations docs/vocal-auto-events-benchmark-20261031/model-observations.json \
  --out /tmp/persodub-audio-event-score.json

python -m pytest tests/test_vocal_audio_tag_benchmark.py -q
```

The pure-Python replay above proves arithmetic, source matching, window matching and the reported results **from frozen real model observations**. It is not a fresh inference.

To inspect the selected source links without downloading anything:

```sh
python -m tools.vocal_bench.download_selected \
  --manifest docs/vocal-auto-events-benchmark-20261031/selected-source-manifest.json \
  --out /tmp/persodub-selected-audio --dry-run
```

Remove `--dry-run` only for a deliberate fetch of exactly these **32** WAVs and four original NUS TXT alignment files (not entire source corpora). The download tool validates the published SHA-256 and byte count before accepting each file and uses source-ID-derived filenames to avoid read/sing `01.wav` collisions.

The model IDs, pinned checkpoints, exact runtime versions, source SHA and model outputs are in the numeric snapshot. The recorded benchmark results can be replayed without downloading or running model weights.

An **optional re-inference runner** is also provided for the AST classifier. After fetching the selected files, and using the separately installed audio ML interpreter (Torch + Transformers + librosa), execute:

```sh
python -m tools.vocal_bench.ast_tag_selected \
  --sources docs/vocal-auto-events-benchmark-20261031/selected-source-manifest.json \
  --evidence docs/vocal-auto-events-benchmark-20261031/model-observations.json \
  --source-index /tmp/persodub-selected-audio/source-index.json \
  --audio-root /tmp/persodub-selected-audio \
  --model-dir /path/to/pinned/MIT-AST-model-snapshot \
  --out /tmp/persodub-fresh-ast.json
```

The runner refuses a model whose weight SHA differs from the pinned file. It supports repeated `--source-id` options to rerun only selected pairs. **Two NUS same-song read/sing files were freshly downloaded with SHA validation and re-inferred on the Mac; both AST category rankings and all recorded seven group scores were byte-for-byte equal to the frozen numeric observations.** This verifies an actual bounded audio+model replay, not only arithmetic from a JSON fixture.

Original media and model weights are intentionally omitted from Git.

Further source information:
- [SenseVoice event/emotion upstream](https://github.com/QwenAudio/SenseVoice)
- [AudioSet event ontology](https://github.com/tensorflow/models/blob/master/research/audioset/yamnet/yamnet_class_map.csv)
- [SUPERB speech emotion model](https://huggingface.co/superb/wav2vec2-base-superb-er)
