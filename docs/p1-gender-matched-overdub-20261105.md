# P1-N: Lower Russian Overdub gain and match the original speaker's speaking register

Date: **2026-11-05**. Based on P1-M (draft PR #56) after actual owner evaluation of the local comparison.

## Feedback and observed root cause

The user reported two independent defects in the **real video**, not in isolated TTS clips:

1. Russian dub plays **too loudly relative to the original**.
2. The English source instructor has a male-speaking voice, but the generated Russian speech was female.

In P1-M, `app/engines/voxcpm2_ru.py` bound the first source group `VOICE_01` to female `kseniya`, and the second to male `aidar` **without inspecting the speaker**. That was an ordering bug, not evidence of female speech. The source-overdub mix used `OverdubLevels(original=-16 dB, translation=-2 dB, fade=25 ms)`.

## Actual corrected 234-second videos on Mac

Private source and outputs (not in Git): `~/Documents/PersoDub-Research/reports/p1-voxcpm2-overdub-20261105/`.

Corrected experiment: `male-voice-quieter-20261105/`. Listen using `male-voice-quieter-20261105/index.html` from the existing LAN report server (during the investigation, `http://192.168.0.30:18772/male-voice-quieter-20261105/index.html` answered HTTP 200).

The **same two exact Russian scripts**, source A4 research partitions, original input SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322` and same 234.684-second video clock are retained. Only the TTS voice reference and Overdub gain profile change:

| Parameter | P1-M previous | P1-N corrected |
| --- | --- | --- |
| Source instructor | One male speaker (owner-confirmed) | Same |
| VoxCPM2 Russian reference | female Silero `kseniya` | **male Silero `aidar`** |
| Silero control | female `kseniya` | **male `aidar`** |
| Dubbed Russian under TRANSLATE | -2 dB | **-8 dB** |
| Source original under TRANSLATE | -16 dB | -16 dB |
| When TTS stops | Original recovers promptly via voice activity | Same |
| Research TRANSLATE intervals | 0.35-8.90 and 49.12-55.50 s | Same |
| All other intervals, including vocal exercises | REVIEW / preserved | Same |

Real final files:

- `male-voice-quieter-20261105/voxcpm2_male/research_bilingual.mp4`
- `male-voice-quieter-20261105/silero_male/research_bilingual.mp4`
- The same folder holds 62-second preview videos, audio-only m4a for each engine, `index.html`, source-voice receipts, per-video technical SHA receipts and reproducible local render scripts.

**Actual technical verification for both newly rendered videos:** 7,039/7,039 source video packet SHA256s exactly match original, 10,107/10,107 source AAC packet SHA256s exactly match original, **219.703 s of 48 kHz original PCM outside the two translated windows are byte-identical**; the final MP4 has separate Overdub and Original selectable audio tracks. These checks do not establish that every singing/speech interval in the full lesson has a human-approved A4 decision. This remains a source-bound *research* sample.

## Product code change

### New quiet defaults

- `app/audio/overdub.py`: default original speech -16 dB (unchanged), translated Russian speech **-8 dB** (was -2). Original-only intervals still have exactly the original PCM and zero dub samples.
- `app/api/overdub.py`: draft/export defaults agree with the mixer.
- `app/vocal_overdub_export.py` and the mixer CLI: defaults agree with the mixer.
- `static/index.html`: Advanced Overdub level control starts at -8, not -2.
- **Previously saved user drafts retain their explicitly stored levels** (including old -2), rather than silently rewriting approved mixes. A re-export can choose -8 explicitly in the dialog.

### Source register assignment, not group-order assignment

- `app/source_voice_register.py` is a small source-only voice-register router, called once before native fixed-Russian voice assignment. It uses **only portions of actual approved translated speech windows**; songs/vocal demonstrations outside those windows are not used for voice-register inference.
- `app/scripts/source_voice_register.py` reuses the pre-existing `DIAR_PYTHON` / engines environment, where `librosa`, NumPy and soundfile already exist. It loads only up to three bounded short speech snippets per voice group, extracts voiced F0 using `librosa.pyin`, and classifies lower quartile speaking pitch: **up to 150 Hz -> male-sounding voice bank**, **from 170 Hz -> female-sounding bank**. 150-170 Hz or insufficient voiced evidence requires an explicit reviewed voice-register override. These are coarse acoustic register indicators, **not claims of personal identity or sex**.
- Job-local `russian_source_voice_registers.json` records evidence, spans and method. The job-local, manually reviewed override `russian_voice_register_overrides.json` can explicitly select male or female source-sounding voice for a named TTS voice group, taking priority over automatic analysis. Format:

```json
{"version":1,"speaker_to_register":{"VOICE_01":"male"}}
```

- `VoxCPM2RuEngine`: Russian male reference `aidar` for male-sounding source, Russian female `kseniya` for female-sounding source, **regardless of speaker order**. If two distinct speakers need two male/female presets but this pilot bank has only one, the job asks for additional verified voices; it no longer gives one the wrong register.
- `SileroRuEngine`: male `aidar`, `eugene`; female `kseniya`, `xenia`, `baya` (five existing native presets). Distinct same-register speakers retain distinct presets where available. Direct legacy engine tests can still call without source evidence, but **product pipeline now passes source register evidence**.
- `app/engines/base.py` extends its existing `assign_voices` contract with optional `source_registers`; this avoids another parallel voice assignment system. Qwen source-timbre cloning is unchanged.
- `app/pipeline.py` updates the A4 TTS fingerprint with `source_pitch_or_explicit_v1` for native preset engines, so older female P1-M cached lines cannot be mistakenly treated as new male voice audio.
- `app/api/overdub.py` uses the original job's selected voice engine for selective redub preflight, rather than unconditionally requiring Qwen when the job uses VoxCPM2.
- `app/vocal_overdub_regenerate.py` copies any source-reviewed register override into a new source-identical selective-TTS job alongside the immutable source caches.

### Verified source classification on the actual lesson

Using the existing separated source `vocals.wav` and speech portions at 0.5-6.0 s and 49.27-54.7 s, the real worker measured **lower-quartile speaking F0 108.49 Hz** (individual speech snippet values 104.42 Hz and 112.56 Hz). The running external VoxCPM2 server responded on Mac and the full product bridge actually returned `VOICE_01 -> male -> aidar`. A separate 5.6-second Russian female `kseniya` reference was classified as female-sounding at **177.91 Hz** using the same inference worker, confirming the detector is not hard-wired to male.

The acoustic F0 policy has not been independently calibrated across broad languages, ages, singing styles, or speakers with unusual pitch. The explicit reviewed override is the supported way to resolve ambiguous groups. This is **not** an identity classifier and does not claim to infer personal sex from audio.

## Independent Russian readback on the corrected male voice WAVs

The same local independent Whisper Large-v3 CPU/int8 decoder re-read the four actual newly generated male voice WAVs against their exact unchanged Russian script:

| Voice | First line (12 words) | Second line (10 words) |
| --- | ---: | ---: |
| VoxCPM2 conditioned on `aidar` | 0 ASR edits | **2 ASR edits** |
| Silero preset `aidar` | 0 ASR edits | **0 ASR edits** |

For VoxCPM2 the second readback began `пепении нужен баланс`, where the given text was `В пении нужен баланс`. This could be a synthesized onset issue or a Whisper readback error; actual native Russian human adjudication remains NOT_RUN. The corrected output is **not** claimed to have 0 WER just because the voice-register match and stream integrity now pass. The full bounded readbacks and every source WAV SHA are in private `male-voice-quieter-20261105/male-tts-readback.json`.

## Verification and status

Focused tests cover precise mixer sample amplitudes for the new -8 dB default; source speaker labels, reviewed overrides, approved-only bounded excerpt selection, ambiguous evidence requiring review, explicit stable per-source gender register in both engines, native voice bank limits, genuine VoxCPM2 server preflight during selective Overdub, and preserving reviewed overrides into a new job. Legacy native-voice and Overdub expectations were updated for the new default profile; source-only protected windows remain bit-identical.

**Verification run on the Mac against this branch:** `277/277` adjacent Python tests PASS (`pytest`, isolated p0 FastAPI venv) and `1168/1168` UI tests PASS (`node --test ui/src/*.test.mjs`). Python `compileall`, Ruff and `git diff --check` were also executed successfully. Actual local source male/female pitch classification and the VoxCPM2 server handshake were exercised independently of the unit mocks; both corrected full MP4s have source packet/PCM receipts. All private logs and source voice waveform SHA are retained in the P1-N report folder. **Existing Qwen model and default TTS choice are unchanged. No background synchronization, no GitHub Actions, no private media or model weights are committed.**

Next quality gate: human listening to the new male source-mixed 62-second clip for loudness and naturalness before generating longer vocal lessons. The owner already confirmed the first instructor's voice is male; an independent A4 review of the full 234-second source is still outstanding.
