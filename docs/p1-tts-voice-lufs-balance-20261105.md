# P1-Q: English Russian translation too quiet after base LUFS normalization

Date: 2026-11-05. Stacked on P1-P #59. Focus: measured loudness, no new voices/ASR/translation.

## Defect reproduced on real owner lessons

User preferred **-16 dB** after the source programme was normalized, but the English lesson's Russian voice was almost inaudible. The source-level P1-P correction was sound; the underlying Russian TTS programme levels were not equal.

**All values below were measured on the exact real voice-only 48kHz PCM of the three owner's lesson comparison videos, not inferred from captions or test fixtures.**

| Voice-only source | Actual TTS integrated LUFS (EBU R128 input_i) | 100-ms spoken-only RMS | Base under active TTS RMS |
| --- | ---: | ---: | ---: |
| English full 234.633s WAV, male Silero aidar | **-25.15 LUFS** | **-26.74 dBFS** | -24.87 dBFS |
| German first 80s, male Silero aidar | -14.75 LUFS | -16.74 dBFS | -25.12 dBFS |
| Spanish first 80s, female Silero kseniya | -14.96 LUFS | -17.30 dBFS | -24.48 dBFS |

The English voice-only WAV was about **10 LU quieter** than the other two. The fixed -16 dB user control attenuated it yet again: in English the Russian voiced-window RMS would become about -42.74 dBFS, below the original under-speech RMS near -40.87 dBFS; in German the RU voice after -16 was near -32.74 dBFS, much louder than its original under-speech.

## Minimal product fix

- Reuse **`app/audio/loudness.py`**, FFmpeg's already installed EBU R128 `loudnorm` input meter. `measure_overdub_voice_loudness(voice_wav, cache_path)` operates on the **voice-only WAV with real pauses**; integrated EBU loudness gating avoids evaluating the long silent duration as programme volume.
- Use **-15 LUFS voice-only** as the common calibrated reference because German (-14.75) and Spanish (-14.96) were already owner-preferred at a -16 dB setting. Do **not** change the source -22 LUFS normalization or the user's requested -16 dB.
- Store one SHA256/source-frame/profile-verified compact voice level receipt for each unchanged voice WAV, reused across multiple gain choices. Reject misbound calibration from a different voice take; invalidate when the WAV changes.
- No new normalized TTS WAV. **Apply the static compensating gain inside the existing PCM mixer**, after the user-selected voice dB. The existing sum-of-gain peak ceiling remains enforced, including for user-selected unusually high levels. Silence-only REVIEW/PRESERVE projects get 0 dB compensation.
- Corrected real input values and mixer gain at user setting -16 dB: English compensation **+10.15 dB** -> effective TTS gain **-5.85 dB**; German compensation -0.25 dB, Spanish -0.04 dB. This is a *measured, input-specific correction*, not a new global preset for all voice models.
- Product pipeline, existing-job re-export, source-first S2ST short preview and direct mixer CLI all use one helper. The source A4 SHA clock and human-confirmed actions remain authoritative. The untouched original audio is still the separate second MP4 track. No added UI control.
- The corrective gain is global to the full voice-only stream; it preserves **within-video** emphasis, tone and speech pacing. Multispeaker per-speaker perceived loudness is a separate later quality objective, not part of this fix.

## Actual re-render of English lesson

Private Mac folder: `~/Documents/PersoDub-Research/reports/p1-voxcpm2-overdub-20261105/normalization-evidence-20261105/english-voice-corrected-20261105/`.

Actual first 72-second compressed audio controls, full 234.684-second bilingual MP4 and source-video comparison page (LAN during test):

`http://192.168.0.30:18772/normalization-evidence-20261105/english-voice-corrected-20261105/index.html`

- Existing source transcript **32/32** Russian voice cues reused; exact existing Silero WAV SHA `12ef276e760887b1cb47364701e5da6652af18e4d355f0d8c2c500dda1b3fa93`. **No new TTS or translation.**
- Both videos have the exact original video **7039/7039** packet SHA256s and original AAC **10107/10107** packet SHA256s; the corrected video has Overdub selected by default, Original as the unchanged second audio stream.
- User requested level stays **-16 dB**; source base stays **-21.97 LUFS**. Calibrated TTS is measured against **-15 LUFS**.
- **Actual mixed PCM RMS during 1373 100-ms voice-active windows:** old **-35.01 dBFS**, corrected **-31.08 dBFS**, a +3.93 dB rise in the *combined* audio. Isolated Russian voice contribution increased **+10.15 dB**, eliminating the prior under-original disadvantage.
- **Protected A4 content:** 29 protected intervals spanning **2,003,664** actual 48kHz audio frames are byte-identical to the normalized original source in the corrected output. The full existing research A4 plan did not change, and source clock length is identical.
- `real-english-calibrated-qa.json` and `calibrated-acoustic-comparison.json` capture the exact identity and acoustic tests. Native Russian human loudness and source-word/A4 final approval have not been executed.

## Verification

`tests/test_overdub_voice_loudness.py` performs real-FFmpeg tests for a roughly 10 dB difference in synthesized voice amplitudes rendered at the same user-selected -16 dB, cache reuse/invalidation, source SHA and A4 identity, silence fallback, and peak-gain ceiling for a high-volume user selection. Product adjacent real-source test suite **294/294 Python tests PASS**; actual new A4/dual-track MP4 re-render verified. The UI test status must be recorded from a fresh run on this exact branch; previous branch results do not automatically transfer.

**Next action:** listen to the short old-versus-corrected audio controls and verify that the new English -16 dB now has the same intelligibility as the already preferred German/Spanish -16 dB. No PR merge to `main` automatically.
