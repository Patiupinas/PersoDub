# PersoDub P1-B: cross-language speaker similarity control result

**Recorded:** 2026-11-02, Mac M1 Max. **Parent:** Draft PR #43 `feature/vocal-quality-benchmark-selection-20261102`. **Scope:** source English instructor to Russian Qwen3-TTS. Separate read-only, private, CV3-**style** speaker embedding diagnostic, NOT the official CV3-Eval scorer and NOT native Russian speaker quality acceptance.

## What was done

The official [CV3-Eval](https://github.com/QwenAudio/CV3-Eval) proposes independent text consistency (WER/CER), speaker similarity (ERes2Net embedding cosine) and DNSMOS audio quality. PersoDub already had real three-way Qwen3-TTS variants on **three identical source-clock Russian lines** with fixed target wording/seed (old SPK0 reference + timbre, new 6.56s source SPK0 reference + timbre, and new source reference + ICL). We explicitly **did not** use the model that generated the voice as its own oracle.

The Mac had an existing *different* speaker verification model, `microsoft/wavlm-base-plus-sv` / `transformers.WavLMForXVector`. Its model weights and config were cached in the local HF hub. The private local runtime placed symlinks to the two cached files without making any new model download or shipping them with PersoDub. It scored original speaker samples and Qwen voices with the **same raw PCM, mono/16k resampling, model and embedding normalization**.

The new standalone `benchmarks.persodub.speaker_similarity_eval` accepts a frozen manifest with source/target languages, **two original source time-disjoint reference WAVs**, an external Russian WAV as a deliberately *assumed* nonmatching control, matched target texts/seeds/slots and 9 genuine TTS WAV files. It verifies local files, hashes, WAV duration and distinct paths; it refuses unpaired/mismatched test variants, silent/nonfinite outputs and malformed model embeddings. `--model-dir` must be an existing local folder with `config.json` and `model.safetensors`. `local_files_only=True` is mandatory. The rest of the application never imports PyTorch or downloads a model merely to enumerate benchmark modules.

**Input provenance:**
- Completed 234.684-second private video SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`.
- Older English SPK0 reference duration 6.90s, source `74.78-81.68s`; SHA-256 `4c1abde1077ea11bd95dc0f95ddf840c8528a8b55dbbbadf42861e89a2204a7a`.
- New English speech-dominant SPK0 reference duration 6.56s, source `158.780-165.340s`; SHA-256 `44e7f18398d0f4e03702d5f40ea3ff589a971a89e2d2d0257b531489530a0e95`.
- One separately sourced Russian FLEURS test WAV `fleurs_ru_1694` as the external language/domain control. This is assumed a different speaker because of independent corpus provenance, but **speaker identity has not been independently confirmed**. It is not a certified impostor label.
- Cached WavLM weights SHA-256 `94c3defe08248d81c7b2bd0a058ea9985269cefed13076434669c47fade41182`; local model config SHA-256 `c6ac8c0ce55b18d4612677931036fe5ce78093e87361c552a173f00a0bb07514`.

## Actual local measurement, and why it is not an acceptance metric

| Acoustic similarity proxy | WavLM cosine | Source-slot overruns |
| --- | ---: | ---: |
| Two original English instructor anchors | **0.932649** | N/A |
| Original English old reference vs unrelated Russian FLEURS control | **0.609644** | N/A |
| Original English new reference vs unrelated Russian FLEURS control | **0.676043** | N/A |
| Qwen, old English reference / timbre, mean to both original anchors | **0.749552** | 0/3 |
| Qwen, new English reference / timbre, mean to both original anchors | **0.790715** | 1/3 |
| Qwen, new English reference / ICL, mean to both original anchors | **0.836450** | 0/3 |

**Critical independent countercheck:** on **8 of 9** generated Russian WAVs, similarity to the *unrelated Russian FLEURS* clip was **higher than the mean similarity to the two English instructor references**. The ninth clip did not exhibit that ordering. The original English source anchors match each other more strongly than the Russian control, but this does **not** establish cross-language discrimination. This is consistent with model sensitivity to language/domain/recording conditions, although the specific cause is not proven with one external control.

**Interpretation:** WavLM ranks the three configurations on this small matched test, **but the independent cross-language counterexample invalidates treating that order as speaker-identity fidelity or selecting a winner**. The benchmark returns `OBSERVED`, `CONFLICTING_LANGUAGE_OR_SPEAKER_PROXY`, `unrelated_control_closer_cases=8`, and `speaker_similarity_model_selection_validated=false`. These fields are contract tests. No subjective or official CV3-Eval PASS is claimed.

The previous independent Russian ASR and time-slot observations (old/timbre 1/25 WER, new/timbre 0/25, new/ICL 1/25; the new/timbre short line overran by 0.20s) are still valid *for those specific three Russian utterances*. They do not repair the invalid speaker-similarity oracle or prove Russian accent and natural pauses.

## Reproduce without changing the original job

The private exact inputs, source audio, selected model files and unmasked score report are all on the Mac under `~/Documents/PersoDub-Research/reports/p1-speaker-sim-20261102/` and `~/Documents/PersoDub-Research/reports/p1-quality-benchmarks-20261102/cached-wavlm-model/`. Private manifest `source-frozen-nine-candidates-v2.json`, read-only output `wavlm-cv3-style-nine-voices-validated.json`.

```sh
cd ~/Documents/PersoDub-Research/worktrees/p1-speaker-sim-20261102
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  ~/.persodub-dev-kit/engines_venv/bin/python \
  -m benchmarks.persodub.speaker_similarity_eval \
  --manifest ~/Documents/PersoDub-Research/reports/p1-speaker-sim-20261102/source-frozen-nine-candidates-v2.json \
  --model-dir ~/Documents/PersoDub-Research/reports/p1-quality-benchmarks-20261102/cached-wavlm-model \
  --out ~/Documents/PersoDub-Research/reports/p1-speaker-sim-20261102/recheck-new-output.json
```

The report is one-use `x` file creation, no overwriting past scores or original media. Tests use a fake injectable encoder for identity/control contracts; the 9 real audio clips were separately decoded with the existing fully cached WavLM model. No original / Qwen WAVs, dataset samples, full video, pretrained checkpoint or private speaker embeddings are committed to Git.

## Next validation hinge

**Next** compare the *same frozen nine wavs* using **the official ERes2Net (CV3) speaker scoring backend or a separately cross-language-validated speaker model with verified same-speaker and different-speaker control clips**. It must distinguish real English/Russian same-speaker audio from cross-speaker Russian/English without a language shortcut; only then can a speaker-similarity proxy inform a model choice. In parallel, the native-Russian blind review pack (PR #42) remains **NOT_RUN** and the complete lesson A4 speech/singing boundaries remain **NOT_RUN human gold**. Never promote a model-only similarity ranking to A4 acceptance.
