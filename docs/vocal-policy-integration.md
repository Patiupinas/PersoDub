# Policy-to-PCM integration: synthetic contract check

This is a **model-free integration test**, not a singing detector or a claim of
accurate vocal recognition. It is stacked on draft PR #1 (decision schema),
#2 (PCM assembler), #3 (safety benchmark), #4 (offline tone fixture), and #6
(conservative vote policy). Do not merge the integration PR before its
upstream dependencies have been reviewed and merged.

## Data flow and invariants

1. `app.vocal_offline_demo.create_demo()` generates a deterministic stereo
   PCM16 WAV, fake short TTS tone WAVs, and an **independently defined** gold
   `decisions.json` representing German explanation, a vocal example,
   English explanation, then an uncertain segment.
2. Pre-aligned JSON windows present ASR text and declared votes from two
   *placeholder* acoustic model IDs. `select_vocal_decisions()` must return a
   fully covering, version-1 schema-valid manifest. Contradictory votes yield
   `REVIEW`; no model weights are loaded.
3. `assemble_vocal_wav()` consumes that manifest, replacing only translated
   frames and copying original `PRESERVE/REVIEW` PCM bytes.
4. `verify_preserved_wav()` compares every gold protected PCM frame, while
   `score_vocal_decisions()` independently evaluates false-TRANSLATE risks and
   translation utility over exact integer sample boundaries.

## One test command

```bash
python -m pytest --noconftest -q \
  tests/test_vocal_decisions.py \
  tests/test_vocal_pcm.py \
  tests/test_vocal_benchmark.py \
  tests/test_vocal_offline_demo.py \
  tests/test_vocal_policy.py \
  tests/test_vocal_policy_pipeline.py
```

The test validates both **safe** and intentionally **unsafe** predictions:
- A disagreement about spoken text must become `REVIEW` and decrease speech
  recall, rather than silently replacing the audio.
- ASR can hallucinate a word over a sung-vowel placeholder; if acoustic votes
  identify vocal, the policy must not translate it.
- If *both* acoustic models are wrong, the policy **can** translate vocal
  material; a separate, correct gold benchmark must then flag unsafe audio.
- A one-sample late boundary can corrupt preserved PCM. Gold scoring detects
  the wrong decision and PCM verification rejects the rendered WAV.

The WAVs contain **synthetic oscillators**, no speech or singing. A green CI
proves the interfaces and guardrails are correctly wired at the PCM stage,
not classifier accuracy, intelligibility, original voice similarity, or
final MP4/AAC synchronization. Never include purchased lectures, speaker
references, voiceprints or customer media in a public Git repository.
