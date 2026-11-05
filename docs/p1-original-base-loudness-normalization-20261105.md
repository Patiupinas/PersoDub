# P1-P: normalize original base loudness before choosing Russian voice gain

**2026-11-05.** Based on P1-O PR #58, kept as an independent draft.

## Owner's correction and observed real recordings

The owner correctly noted that `-16 dB` versus `-20 dB` on the Russian voice is not a valid cross-video comparison until the **original base tracks** have a consistent perceived loudness.

Actual first-pass FFmpeg EBU R128 measurements on authorized Mac:

| Original speech lesson | Raw integrated LUFS | Raw true peak dBTP | Normalized integrated LUFS | Normalized true peak dBTP | Mode |
| --- | ---: | ---: | ---: | ---: | --- |
| English, full 234.684 s video | -22.87 | +0.03 | **-21.97** | -1.50 | dynamic |
| German, 80 s source | -27.23 | -8.48 | **-22.00** | -3.25 | linear |
| Spanish, 80 s source | -26.04 | +0.03 | **-22.12** | -1.50 | dynamic |

All measured values come from the project's exact actual original 48 kHz stereo PCM source files. The source loudness spread before normalization was **4.36 LU**; after normalization it is **0.15 LU** in the final product-helper executions. Earlier standalone preflight render measured -21.89 LUFS for German instead of -22.00, both are consistent with a two-pass measurement/dither difference; the normalized research comparison page uses the product-helper outputs recorded above.

This is a measured project-specific target of **-22.0 LUFS**, **-1.5 dBTP**, target LRA=20. The underlying EBU R128 broadcast recommendation specifies **-23 LUFS**, which we are *not* claiming to implement as a broadcast release target. Reference: https://tech.ebu.ch/docs/r/r128.pdf . Integrated loudness and true peak are measured over the whole programme rather than speaker-only segments, per EBU guidance. Because the English and Spanish source peaks were around 0 dBTP, fixed upward gain would have exceeded the chosen peak ceiling; actual FFmpeg selected its dynamic mode. German could use fixed-gain linear normalization.

## Architecture and invariants

- **Single source of normalization truth:** `app/audio/loudness.py` using project-installed FFmpeg `loudnorm` with two passes and a measured output check, not a new audio dependency or separate provider. No per-speaker/offline recording normalization duplicates.
- **Source clock:** source WAV must be 48 kHz stereo PCM16. Output must have *exactly the same sample-frame count*, sample rate and channels. FFmpeg can process `loudnorm` internally at 192 kHz; therefore `aresample=48000` is placed **before** `atrim=end_sample=N`. The first real experiment mistakenly trimmed at the internal filter sample rate and produced 1/4 of the expected duration; this ordering was corrected and now has sample-count regression tests.
- **One baseline, multiple mixes:** `normalize_overdub_base(raw, normalized, receipt)` writes a distinct, derived WAV with an atomic sidecar. The receipt is keyed by source WAV SHA256, exact profile version, frame count and normalized WAV SHA256. A subsequent `-16/-20 dB` export reuses the same normalized base without a fresh analysis or altered gain.
- **A4 authority remains raw original:** `overdub_events.json` still binds to the raw decoded source SHA256. The normalized base is validated against that exact source and keeps the source clock, but does not rewrite it.
- **Overdub audio:** mixer `render_overdub(..., normalized_source_wav=..., source_normalization=...)` uses the normalized base for all `TRANSLATE`, `REVIEW` and `PRESERVE` regions. The A4 translation permissions are unchanged. `PRESERVE`/vocal exercises remain **original content with zero Russian TTS**, albeit at globally normalized source programme loudness, not the exact old raw amplitude. The separate selectable **Original MP4 stream** remains the source video's packet-identical, unnormalized audio.
- **Traceability:** mixer receipt carries measured input/output LUFS, true peak, normalized WAV SHA and original raw SHA. Old raw mixer calls without normalized audio remain supported for explicit legacy/low-level testing.
- **Call paths:** the complete Overdub product pipeline, existing-job re-export/API, direct mixer CLI (default normalize; `--raw-base` explicit legacy override) and experimental S2ST short preview all use this owner. Qwen/Silero/VoxCPM TTS generation and translations are unchanged.
- **No new UI bureaucracy:** target fixed to -22 LUFS for this experiment; -16/-20 dB remains a single existing Russian-gain choice. Saved explicit voice-gain drafts remain respected. Original source and original MP4 are never overwritten.

## Real end-to-end normalized videos

Private Mac results only:
`~/Documents/PersoDub-Research/reports/p1-voxcpm2-overdub-20261105/normalization-evidence-20261105/`

**Listening URL during live LAN session:** `http://192.168.0.30:18772/normalization-evidence-20261105/index.html` .

The comparison contains **six actual MP4s**:

- English 234.684 s lesson, existing **32/32** source-transcript male Silero `aidar` speech (P1-O A4 *research* plan, not human gold), same normalized original baseline, two Russian gain variants -16 and -20 dB. Both videos retain **7039/7039 source video packet SHA256** and **10107/10107 original AAC packet SHA256**.
- German first 80 s, male Silero `aidar`, **22/22** candidate cues, same German normalized base, two gain variants. Each retains **960/960 video** and **3751/3751 source AAC** packet hashes.
- Spanish first 80 s, female Silero `kseniya`, **12/12** candidate cues, same Spanish normalized base, two gain variants. Each retains **960/960 video** and **3751/3751 original AAC** packet hashes.

Research original PCM and video identities remain untouched. Private reports at `{lang}/base-loudness.json` and `{lang}/normalized-base-russian-minus{16|20}-audit.json` store source hashes, output waveform hashes, loudnorm mode, and mux packet QA.

**Zero clock-shift check:** before product integration, 15 independently sampled one-second real-audio windows across three source languages all had **lag 0 samples** after normalization. The exact number of final 48 kHz samples was identical before/after in each complete source. See private `alignment.log` and `{lang}-two-pass-probe.json`.

## Regression and limitations

- Unit/regression tests in `tests/test_overdub_source_loudness.py` cover real two-pass FFmpeg, two different input amplitudes to the same target, caching, invalidation on source changes, raw/normalized A4 SHA mismatch, same-sample source-only preservation and two different dub gains using the *same* baseline.
- Existing source-only A4 mixer assertions change intentionally from `Overdub.PRESERVE == raw original PCM` to `Overdub.PRESERVE == normalized base PCM`; the selectable Original stream remains raw/packet-identical. The full A4 action plan is immutable.
- True-peak-limited normalization may use dynamic mode (English/Spanish). Actual waveform cross-correlation remained 0-sample aligned. This does change the waveform amplitude of source singing/exercises in the Overdub track; it does not create synthetic singing or touch the second Original track.
- Matching integrated source LUFS **does not by itself make TTS voices equally loud**, because Silero/VoxCPM voice presets have their own speaking level. TTS preset matching can be measured next, but no speculative second normalizer is introduced in this fix.
- Current full English 32/32 and DE/ES 22/22, 12/12 counts refer to *current ASR source cues*, not independently verified word coverage or human A4 singing truth. Those limitations are unchanged.

**Next gate:** owner listens to the normalized-base 6-video comparison, choosing -16/-20 from a fair common-source target. No speculative automation or new A4 review process is introduced. Do not merge to main without owner instruction.
