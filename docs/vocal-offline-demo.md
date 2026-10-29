# Offline synthetic vocal dubbing demo

**Status:** model-free integration fixture. This is not real singing, translation,
or a test of any neural model. The WAV inputs contain generated tones only.

The command exercises three independent draft components together: decisions
(PR #1), protected PCM assembly (PR #2), and frame-weighted safety benchmark
(PR #3). It produces reproducible, **local** small WAVs and JSON reports.
It downloads no weights or datasets, calls no network APIs, and leaves the
standard PersoDub pipeline untouched.

## Run

Requires Python 3.11 or 3.12 and the Python standard library. From repo root:

```bash
python -m app.vocal_offline_demo --directory ./demo-vocal-synthetic
```

The target directory must be new or empty. The command refuses to overwrite
existing files. Output includes:

- `original.synthetic.wav`: four-second decoded PCM16 stereo at 48 kHz.
- `speech-de.synthetic.wav` and `speech-en.synthetic.wav`: shorter replacement tone WAVs (TTS stand-ins only).
- `gold.synthetic.json`: independent ground-truth *structure* with a MIXED parent, translated explanatory placeholders, a protected sustained-tone region and an explicit REVIEW region.
- `predicted-safe.synthetic.json`: a prediction with no false TRANSLATE.
- `predicted-unsafe.synthetic.json`: deliberately moves a boundary one sample into the protected tone.
- `dubbed.synthetic.wav`: sample-accurate assembled output using the safe manifest.
- `report.synthetic.json`: PCM hashes and protected/translated frame counts, plus one-frame unsafe-prediction detection.

Verify the safety guard separately:

```bash
python -m app.vocal_benchmark --gold demo-vocal-synthetic/gold.synthetic.json --pred demo-vocal-synthetic/predicted-safe.synthetic.json --fail-on-unsafe
# expected exit 0 (synthetic safe example)

python -m app.vocal_benchmark --gold demo-vocal-synthetic/gold.synthetic.json --pred demo-vocal-synthetic/predicted-unsafe.synthetic.json --fail-on-unsafe
# expected exit 1 (ONE original protected frame incorrectly marked TRANSLATE)
```

For integration tests (no media, network or model weights needed):

```bash
python -m pytest tests/test_vocal_decisions.py tests/test_vocal_pcm.py tests/test_vocal_benchmark.py tests/test_vocal_offline_demo.py -q
```

The artificial speech portions contain tones, not DE/EN language. The file
labels describe **how the intended real system would treat the regions**, not
what an acoustic model would actually classify. The scripted gold/prediction
is only a deterministic test oracle for assembly, comparison and error paths.

## Safety limitations

- No inference, classification, dubbing model, target language or speaker identity is tested here.
- Input PCM zero must be mapped to video PTS by a future ingest adapter.
- Rendered PCM is not final video; lossless protected intervals may change when encoded as AAC/MP4.
- The TTS placeholders have no real ambience or room tone. A later mixer must reintroduce suitable background on TRANSLATE *without processing protected original sound*.
- Do not publish generated recordings as vocal or dubbing performance results. Do not add commercial lecture footage or cloned voices to Git.
- Actual benchmark acceptance needs separately annotated German/English gold with independent, speaker-disjoint holdout sets.

The GitHub test workflow runs these model-free checks on supported Python
versions without requiring remote user computers. If the fork has disabled
GitHub Actions, results remain **unverified in CI** until it is enabled.
