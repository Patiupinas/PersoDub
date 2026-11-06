# P1-R - owner-selected expressive VoxCPM2 in the original instructor's voice

**Decision:** 2026-11-06. The owner listened to the locally generated EN/DE/ES Russian voice comparisons and explicitly selected **"VoxCPM2 с управлением интонацией"** as the preferred voice quality. That exact experiment used the source instructor's own audio as a reference and the text prefix `(воодушевлённо, с энергичной поддерживающей интонацией)` immediately before the Russian sentence. Do not confuse this with the **older VoxCPM2 RU fixed `aidar`/`kseniya` bank**, whose timbre does not derive from the original instructor.

## Implemented contract

- New opt-in engine ID: `voxcpm2_expressive_ru`, in `app/engines/voxcpm2_expressive_ru.py` behind the **existing** project `TTSEngine` socket. Does not replace `qwen3_tts`, `silero_ru`, or the separate fixed-Russian `voxcpm2_ru` engine.
- The voice stage reuses `build_speaker_refs` to extract one **4-7 s** contiguous source-language speaker sample from the real vocals stem, and persists it as `qwen_ref_<speaker>.wav`. Speaker labels remain the original diarization labels. `assign_voices` requires all active speakers to have such a sample, binds the speaker map to a source WAV **SHA256**, and records the exact model/style identity in a durable sidecar.
- The existing external VoxCPM2 FastAPI service now exposes `POST /generate-clone` accepting bounded **raw WAV bytes**, not arbitrary service-local file paths. It verifies the original reference SHA256 and accepts PCM16 mono/stereo at 16, 24 or 48 kHz for 3-15 s. The **24 kHz** case is required by actual PersoDub `cut_vocals_span_local` extraction; initial tests used prepared 16 kHz samples, and an actual pipeline reference smoke revealed the mismatch, which is now covered by regression tests.
- The exact approved research style prefix is central in `app/voxcpm2_profile.py`, profile `p1-source-voice-expressive-20261106`. Model: `openbmb/VoxCPM2`, pinned revision `32279effe8c19989596f05d353d1447f51d9e915`; `cfg_value=2.0`, `inference_timesteps=10`, `load_denoiser=False`. The server gives back native 48 kHz PCM WAV, source SHA header and profile ID. `SynthesisRequest.seed` is set via PyTorch and NumPy under the existing model generation lock.
- The engine checks the exact service profile/model revision before taking a job. The TTS identity is part of the A4 resume fingerprint. One-line revoice checks the same model/style identity **and original speaker ref hash** rather than silently revoice with Qwen. Switching provider invalidates stale competing source-clone/fixed-Russian voice receipts so a prior selection cannot take ownership of a later remake.
- Supported target language is Russian only. The user-visible selection appears in the existing Advanced Options TTS stage. Other output-language defaults and selected persisted jobs are unchanged. This remains **opt-in**, not an automatic alteration of every user's Qwen default. No new service framework, UI panel, second owner of timing or A4 approval authority.
- All existing Overdub source loudness -22 LUFS, voice-only loudness -15 LUFS calibration, user `-16 dB` selection, protected A4 singing/actions, original MP4 audio/video packet identities, translations, subtitle clocks and mix boundaries remain owned by the existing code. This feature only changes Russian TTS voice selection, reference and text style.

## User-reviewed acoustic evidence

Private research player: `http://192.168.0.30:18774/`, files at `~/Documents/PersoDub-Research/reports/p1-voice-expression-20261106/`. Three source teachers, English male, German male and Spanish female, with neutral and expressive Russian phrases were compared with Silero, VoxCPM2 and OmniVoice, plus CosyVoice 3. Existing research: 11 source-cloned VoxCPM2 v2 WAVs, 6 OmniVoice v2 and 6 CosyVoice 3 reference-v2 WAVs, fixed Silero controls. The owner explicitly preferred the VoxCPM2 expressive samples by ear. The cached Whisper RU independent readback of the first **11 VoxCPM2 v2 samples** had **0 word mismatches among 106 target words**. This is only a machine-ASR proxy on short samples, not manual Russian speech, A4 or speaker identity truth.

The benchmark TTS inputs, original media, source ref WAVs, weights and comparison web player are private and **must not be put in Git**. Model-embedding cosine metrics are not identity probabilities.

## Actual product-stage proof

The repo's original source-reference extractor was executed on the private 234.684 s lesson vocals, producing a real **6.5 s, 24 kHz mono** `SPK0` voice ref. The production `VoxCPM2ExpressiveRuEngine.assign_voices` stored it, then synthesized the selected Russian phrase through the **real pinned Mac MPS VoxCPM2 service**, not a fake. The service returned a 48 kHz WAV with the correct speaker hash and engine ID. Private evidence: `selected-product-smoke/english-teacher-selected-voice.wav`, `selected-product-smoke/product-voice-smoke.json`, and `analysis/selected-real-product-stage.log`. The source research A4 plan and original movie were not modified.

This proves source voice extraction, provider registration and real source-clone generation. It is not a claim that the full lesson with this new voice has already been rendered, nor that every line's source transcript and A4 exercise boundaries have been manually accepted.

## Validation and launch

- **472/472** adjacent Python suite PASS on this feature branch before the final Windows temporary-directory compatibility adjustment. The exact changed API/service/engine suite was rerun **12/12 PASS** afterward; lint and `git diff --check` PASS. **1168/1168 UI Node tests PASS** after the new selection and i18n keys were added.
- An independent local Whisper large-v3 recognized the actual product-stage synthesized Russian as `А теперь попробуй еще раз. Не спеши, следи за дыханием.`, all ten expected Russian words, with punctuation/`ё` normalization. This is diagnostic machine readback, not a human-naturalness rating.
- Source service now writes temporary references inside `TemporaryDirectory`, allowing the model to reopen the WAV on Windows/macOS and deleting it after synthesis. Old fixed-bank HTTP route kept unchanged.
- Selected actual MPS service on local Mac research port `19101`, separate from historical fixed-bank service at `19100`. To reproduce with a fresh process:

```bash
ROOT="$HOME/Documents/PersoDub-Research"
cd "$ROOT/worktrees/p1-voxcpm2-expressive-source-clone-20261106"
PERSODUB_VOXCPM2_REFS="$ROOT/reports/p1-ru-voice-catalog-20261103/silero-v5-6" \
PERSODUB_VOXCPM2_DEVICE=mps \
HF_HUB_OFFLINE=1 \
"$ROOT/reports/p1-voxcpm2-overdub-20261105/voxcpm-venv/bin/python" \
  -m uvicorn tools.voxcpm2_ru_server:app --host 127.0.0.1 --port 19101
```

Run the PersoDub application with `PERSODUB_VOXCPM2_URL=http://127.0.0.1:19101`, and select **VoxCPM2 source voice + expression (experimental)** for Russian dubbing. There is no automatic model download into the normal app pack and no change to Windows/Mac normal fallback behavior.

## Next quality comparison

Use an actual multi-sentence Russian script from a reviewed source lesson, comparing this source-cloned expressive engine to the previously selected native presets while holding original-normalized and voice-calibrated levels identical. Verify continuous speaker identity, Russian lexical readback and that user-identified singing/exercises have no synthetic replacement. Preserve current draft branch discipline; do not merge into main without owner direction.
