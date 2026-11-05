# P1-M - VoxCPM2 Russian opt-in through PersoDub TTS and real-video comparison

**Later owner correction P1-N (2026-11-05):** The source instructor speaks with a male voice and the female `kseniya` dub in this original comparison is not a voice-register match; Russian -2 dB was too loud. The corrected source-mixed male `aidar` 234-second videos and lower `-8 dB` mix are in the private `male-voice-quieter-20261105` report directory, and the source-aware persistent product change is in `docs/p1-gender-matched-overdub-20261105.md`. The historical P1-M timings and female voice ratings remain observations, not the current output selection.

**Date:** 2026-11-05. **Branch:** `feature/p1-voxcpm2-optin-20261105`, based on Draft PR #55 at `1afa553cf15327b72bc8cfe0e3b9cf9a2b62708d`.

## Motivation and actual selection

The owner listened to the 20 real WAVs in P1-L and gave **5/5 naturalness and 5/5 clarity on each of two recordings** to VoxCPM2 conditioned on the native Russian synthetic female `kseniya` reference. The unconditioned VoxCPM2 and Silero `kseniya` averaged 4.5/5 on both dimensions. This is a direct, individual blind listening result, not independently replicated naturalness MOS. See `docs/p1-ru-tts-model-shootout-20261104.md`.

This branch integrates the selected candidate **only as an opt-in experimental external engine**, without changing the default Qwen3-TTS or removing Silero RU v5.6. Voiceprint cloning of the original English/Spanish/German instructor remains off for this native-Russian pilot.

## Scope and ownership

- `app/voxcpm2_profile.py`: one pinned, immutable profile definition shared by adapter and service. Model `openbmb/VoxCPM2`, revision `32279effe8c19989596f05d353d1447f51d9e915`. The tested voice palette is `kseniya` followed by `aidar`. The research-validated style prefix and inference parameters remain exactly as in P1-L.
- `app/engines/voxcpm2_ru.py`: normal PersoDub `TTSEngine` adapter. No new application-level TTS contract or imports of VoxCPM or torch. `PERSODUB_VOXCPM2_URL` must be explicitly set to the running external service. `/health` must attest the exact model/profile and both reference hashes; `/generate` returns 48 kHz WAV. `VOICE_01` is `kseniya`, `VOICE_02` is `aidar`. A third independent speaker group is not assigned an untested new voice, and fails clearly rather than silently overlapping.
- `tools/voxcpm2_ru_server.py`: separately launched FastAPI server in its **own** VoxCPM Python environment. Startup pins the exact Hugging Face checkpoint revision, reads two **already available Russian sample WAVs**, validates their duration/channel count, and loads VoxCPM2 on the configured device. Its `/generate` retains the exact P1-L style prompt, `cfg_value=2.0`, `inference_timesteps=10`, and `load_denoiser=False`. No source-language voice prompts or cloning.
- Existing project execution paths: `app/dub_launch.py`, `app/pipeline.py`, `app/qwen_pipeline.py`, and `app/api/dub.py` now treat this as a **fixed native Russian TTS** rather than a Qwen source clone. The A4 selective-voice path, real speaker group IDs, single take (no invalid source-similarity best-of-4), original source clock, per-line placement and Overdub mixer stay owned by the existing components.
- Existing `russian_voice_assignments.json` receipt records `engine=voxcpm2_ru`, `source_clone=false`, voice mappings and `engine_identity`. The optional model's A4 voice-resume fingerprint and one-line revoice verify exact model revision and source reference hashes, so switching the reference cannot silently reuse old speech.
- UI: experimental option in Advanced options, setup API, stage picker, saved-job engine label, and model downloader. Selecting the external TTS **does not ask to download Qwen**; API preflight checks the external VoxCPM2 service directly. Legacy default remains unchanged.

## Reproduce on authorized Mac (Metal)

The experiment ran successfully on `Raymonds-Laptop.local`, M1 Max, **64 GiB RAM**. The validated private venv exists at:

`~/Documents/PersoDub-Research/reports/p1-voxcpm2-overdub-20261105/voxcpm-venv/`

The fixed Russian reference directory on Mac is:

`~/Documents/PersoDub-Research/reports/p1-ru-voice-catalog-20261103/silero-v5-6/`

To start this pilot manually from this branch's worktree, set the service process environment:

```bash
export PERSODUB_VOXCPM2_REFS="$HOME/Documents/PersoDub-Research/reports/p1-ru-voice-catalog-20261103/silero-v5-6"
export PERSODUB_VOXCPM2_DEVICE=mps
cd "$HOME/Documents/PersoDub-Research/worktrees/p1-voxcpm2-optin-20261105"
"$HOME/Documents/PersoDub-Research/reports/p1-voxcpm2-overdub-20261105/voxcpm-venv/bin/python" -m uvicorn tools.voxcpm2_ru_server:app --host 127.0.0.1 --port 19100
```

And start PersoDub separately with `PERSODUB_VOXCPM2_URL=http://127.0.0.1:19100` in the application's process environment; explicitly choose `VoxCPM2 RU (experimental external)`. The URL is not an auto-installed or auto-started service.

The pinned /health from the **actually running** Mac service returned `ready=true`, model revision above, `device=mps`, sample rate 48000 and these source-bank SHA256s:

- `kseniya`: `4ea01b9ab34e6d8583f4822f7f93f7eb5e5d31b3df4230cbf009a07955de1482`
- `aidar`: `0388f9bba091816f751e5cb03f021cc9087c44fabcb29df3795b0e05d5ae5b07`

An actual stand-alone MPS probe generated a 4.0 s Russian WAV in 36.221 s (after an initial 191.25 s model-load/download startup). This is **not** a demonstrated sustainable 2-hour Mac throughput rate. Prior P1-L trials on RTX 4090 in WSL succeeded; SunLight's remote command agent was offline during this P1-M implementation, so the current new server implementation has only been executed and measured on the Mac.

## Real video and source audio technical validation

**Source:** original 234.684083 s video `Breath Control for TOTAL Beginners`, source MP4 SHA256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`. No private original video is committed.

The **technical comparison only** places two short, independently generated native Russian fragments into the same source clock:

- 0.350-8.900 s, one speech-only instruction candidate.
- 49.120-55.500 s, a second separate speech-only instruction candidate.

Every other original interval remains marked REVIEW, including the vocal examples near 22 s. The two selected TRANSLATE labels are a **research-only technical hypothesis**, **not human-approved A4**; the main product A4 authority was not changed.

Private reproducible experiment, including exact two-line scripts, all generated WAVs and reports:

`~/Documents/PersoDub-Research/reports/p1-voxcpm2-overdub-20261105/`

- **VoxCPM2**: `voxcpm2/research_bilingual.mp4`, `voxcpm2/technical_report.json`.
- **Silero**: `silero/research_bilingual.mp4`, `silero/technical_report.json`.
- **Short user listening**: `index.html`, the two `*/preview_62s.mp4`, and `voxcpm2_overdub_62s.m4a`, `silero_overdub_62s.m4a`, `original_62s.m4a`.
- Private implementation: `real_video_pilot.py`, `silero_control.py`, independent `asr_voice_audit.py`, and server/probe logs.

Both **real 234 s dual-audio-track MP4s** passed the exact same packet and sample checks:

| Original integrity check | VoxCPM2 | Silero |
| --- | ---: | ---: |
| Video packet hashes unchanged | 7,039 / 7,039 | 7,039 / 7,039 |
| Source original AAC packet hashes unchanged | 10,107 / 10,107 | 10,107 / 10,107 |
| Original 48 kHz PCM outside two voice slots byte-identical | **219.703 s** | **219.703 s** |
| Final video length and two selectable audio streams | PASS | PASS |
| Speaker voice bank for both scripted lines | female `kseniya` | female `kseniya` |

No stretching of either TTS cue was necessary in the placement run. Both source music/exercise windows outside the two voice slots keep the original exact PCM. This proves technical mixer preservation **for this pilot**, not approval of all future A4 source events.

## Independent matched-script Russian readback

Cached independent Whisper Large-v3 (CPU int8), on the raw **real voice WAV**, with the identical submitted Russian script for both engines:

| Engine | First line (12 words) | Second line (10 words) |
| --- | ---: | ---: |
| VoxCPM2 female `kseniya` | **0** errors | **1** error |
| Silero female `kseniya` | **0** errors | **0** errors |

The VoxCPM2 readback of line two starts `Пении нужен баланс` instead of `В пении нужен баланс`: the preposition may have been lost/too quiet, or Whisper may have omitted it. No independent human ear has adjudicated this one-word difference. **Do not claim automatic lexical perfection from the earlier P1-L snippets, even though the owner rated their naturalness 5/5.** Raw per-line SHA/clock and full readbacks are in private `real-pilot-ru-asr.json`.

## Test plan and remaining

- New adapter tests cover explicit opt-in, exact server model/ref identity, no foreign-reference clones, two stable distinct voice groups, missing third voice, native-only target, synthesis contract, forced one take, source-clock A4 cache fingerprint and revoice rejecting a changed voice bank.
- The optional service's fake-model HTTP test covers `/health`, 48 kHz WAV output, exact style+voice parameters, no real model load, bad voice/text and unavailable model.
- Existing Qwen/Silero interfaces, UI setup, voice label, no accidental Qwen downloader, and speech/A4 mixer regression suites are also tested. Record their **actual** counts in the test log before declaring a wider PASS.

**Next one step:** listen to the new **actual source-mixed** VoxCPM2-versus-Silero 62-second comparison. If VoxCPM2 still sounds better with live source context and the one-word first-phoneme readback is corrected, extend the experiment to multiple real source speakers and longer continuous paragraphs while retaining explicit A4 human review. Keep production's TTS default unchanged.

No GitHub Actions, media, checkpoint weights, private complete transcripts, or implicit merge to main.
