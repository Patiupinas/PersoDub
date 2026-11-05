# P1-L - Actual Russian TTS model shootout on RTX 4090

Date: **2026-11-04**, listener rating update **2026-11-05**. Status: **real model-generated audio available, first individual blind listening panel OBSERVED (20/20 scored), independent panel NOT_RUN**. This experiment follows the owner's instruction to improve robotic-sounding Russian dubbing, prioritize several persistent male/female Russian voices for long vocal lectures, and postpone voiceprint matching.

## Hardware, existing project and research artifact locations

- **SunLight**: Windows + Ubuntu 24.04 WSL, NVIDIA RTX 4090 24 GiB. Four model families ran locally; their weights and dependencies are in **isolated** WSL venvs, outside the repository.
- **Mac**: Raymonds-Laptop.local, existing Silero RU v5.6 baseline (CPU) and pinned Whisper Large-v3 ASR oracle.
- **All 20 actual audio samples, manifest with per-file SHA-256, comparison page, independent ASR+waveform report, generator code and logs**: Mac private `~/Documents/PersoDub-Research/reports/p1-tts-model-shootout-20261104/`. Windows originals: `D:\PersoDub-TTS-bench\20261104\`.
- Open offline Mac `index.html` to listen. During this experiment the page also answered HTTP 200 on the local Mac LAN server, with 20 audio players and tested WAV responses.
- No user lesson media, generated WAV, model weights, source voice files, or secret tokens are committed to GitHub.

## Controlled Russian text

Same complete two source-clock-independent Russian texts synthesized in **all** models:

1. `breathing`: "Положи одну руку на живот, а другую на грудь. Сделай спокойный вдох и почувствуй, как опускается диафрагма. Теперь попробуем спеть одну длинную ноту." **23 normalized words**.
2. `lecture`: "Когда мы поём, важно сохранять свободное дыхание. Не напрягай плечи, позволь воздуху двигаться спокойно. Сейчас повторим упражнение и сравним ощущения." **20 normalized words**.

The A/B comparison is **lexically controlled**, but not voice-matched across architectures: some models use random default voices, some are conditioned on exactly the **same synthetic Russian Silero aidar/kseniya 12s reference WAVs**, and Silero itself has fixed native voices. Source synthetic reference can contaminate the target; voice similarity and native prosody remain unverified.

## Models that actually generated WAVs

| Model / trial | Runtime and input | Actual sample rate | WAV duration, breathing / lecture | Independent Whisper errors / 43 words |
| --- | --- | ---: | --- | ---: |
| Silero RU v5.6, `aidar` | CPU fixed voice | 48 kHz | 10.125 / 10.550 s | 0 |
| Silero RU v5.6, `kseniya` | CPU fixed voice | 48 kHz | 10.050 / 10.175 s | 0 |
| VoxCPM2 default | RTX 4090, no voice ref | 48 kHz | 10.560 / 10.720 s | 0 |
| VoxCPM2 + `aidar` | RTX 4090, Russian synthetic ref + style prompt | 48 kHz | 9.760 / 10.880 s | 0 |
| VoxCPM2 + `kseniya` | RTX 4090, Russian synthetic ref + style prompt | 48 kHz | 10.080 / 8.480 s | 0 |
| Chatterbox Multilingual V3 default | RTX 4090, no voice ref | 24 kHz | 9.240 / 8.280 s | **3** |
| Chatterbox V3 + `aidar` | RTX 4090, Russian synthetic ref, expressive params | 24 kHz | 10.960 / 9.800 s | 0 |
| Chatterbox V3 + `kseniya` | RTX 4090, Russian synthetic ref, expressive params | 24 kHz | 10.200 / 9.840 s | **1** |
| ESpeech-TTS-1 RL-V2 standard speed | RTX 4090, Russian synthetic `aidar` ref, F5-TTS | 24 kHz | 6.923 / 7.104 s | 0 |
| ESpeech RL-V2, `speed=0.82` | RTX 4090, same reference | 24 kHz | 8.448 / 8.661 s | **6** |

**ASR protocol**: cached independent `faster-whisper-large-v3` CPU int8, explicit Russian, beam 3, full audio (no VAD filtering), normalized lowercased Russian words with `ё` -> `е`, Levenshtein word edits against the exact input text. Results are persisted per real WAV SHA-256 in `matched-text-asr-waveform.json`. An ASR match measures lexical comprehensibility only; it **cannot** rate how robot-like a voice sounds.

**ESpeech slower variant is a demonstrated defect candidate**, not a recommendation. Whisper transcribed the beginning of `espeech_slow_breathing.wav` as "Положи одно упражнение ещё два раза, положа другую на грудь..." instead of the supplied start. "Упражнение ещё два раза" appears in its synthetic voice reference, suggesting prompt/reference leakage. The same slowed model's lecture sample retained all 20 words. Do not generalize the model's 0 WER at normal speed into safe arbitrary speed controls.

**Other concrete observations**:
- VoxCPM2 completed 2 basic generations: 10.560 s WAV in 15.936 s, 10.720 s WAV in 12.911 s; fixed-reference variants succeeded for two independent target scripts per male/female voice.
- Chatterbox V3 ran only after installation from the official source revision `ab55923c27757c90cfcc407baa57dc25a7d25217`. PyPI `chatterbox-tts==0.1.7` failed with unsupported `t3_model` on `from_pretrained`. Default second generation 8.280 s WAV in 7.656 s.
- VoxCPM2 uses installed `voxcpm==2.0.3` and snapshot `openbmb/VoxCPM2@32279effe8c19989596f05d353d1447f51d9e915`. Unsupported `seed` kwarg removed after observed TypeError; no reproducible-seed claim.
- ESpeech model from `ESpeech/ESpeech-TTS-1_RL-V2@f582b6e5897fe8a5835059405a8439d13bdf7684`, 2.7 GB checkpoint, source `f5_tts.infer.utils_infer` API. Its warmed standard second 7.104 s voice file completed in 1.229 s; first in 3.361 s. Runtime includes reference preprocessing and model load separately.
- No vocal singing/audio mixing here; these are **stand-alone Russian TTS audio probes**, not complete PersoDub bilingual videos.

## Listening and decision procedure

Open private local `index.html`: **10 model/voice conditions x 2 identical scripts = 20 audio players**, blinded labels A-J, each with independent 1-5 ratings for `naturalness` and `clarity`. The page supports downloading `persodub-tts-listening-ratings.json` and revealing source/model labels only after scoring. `listening-manifest.json` records labels, source names, exact filenames, hashes and duration for auditable ratings.

### Owner listening result (uploaded 2026-11-05)

The first completed listening file has `date: 2026-11-04`, 20 unique IDs, and 20/20 ratings for naturalness and clarity. The unmodified source upload's SHA-256 is `1624fa235564bbfe13e64a1987c3b8d81863a04218a9311bc40fd529fc52d9f9`. The raw completed ratings are **private on Mac**, `persodub-tts-listening-ratings-20261105-private.json`, and are not checked into this public repository. These aggregate findings were reconciled with the **frozen SHA-256-bound `listening-manifest.json`**, not an alphabet-based guess; the same A-J blind key applies to both trial texts.

| Blind label | Actual TTS voice/config | Naturalness mean / 5 | Clarity mean / 5 |
| --- | --- | ---: | ---: |
| F | **VoxCPM2 + Russian female `kseniya` synthetic reference** | **5.0** | **5.0** |
| A | VoxCPM2 default / no reference | 4.5 | 4.5 |
| D | Silero `kseniya` female | 4.5 | 4.5 |
| J | VoxCPM2 + male `aidar` synthetic reference | 4.0 | 4.5 |
| E | Silero `aidar` male | 4.0 | 4.0 |
| G | ESpeech RL-V2 `speed=0.82` | 3.5 | 4.0 |
| H | ESpeech RL-V2 standard | 3.5 | 4.0 |
| B | Chatterbox V3 + female `kseniya` reference | 3.0 | 2.5 |
| C | Chatterbox V3 + male `aidar` reference | 2.5 | 3.0 |
| I | Chatterbox V3 default | 2.5 | 3.0 |

Source-level owner ratings for winner F: `breathing` **5/5 nature, 5/5 clarity** and `lecture` **5/5, 5/5**. Silero female control D: `breathing` 5/5, 5/5 and `lecture` 4/5, 4/5. VoxCPM2 male J: 5/5, 5/5 on breathing but 3/5, 4/5 on lecture. This is an individual listening preference, **not** independently replicated native MOS, an acoustic oracle, or a proven long-form product winner. In particular the female `kseniya` voice is **VoxCPM2 conditioned on a synthetic Silero reference**, not a voice natively shipped with VoxCPM2.

A favorable listener score does not erase independently measured defects: ESpeech slower breathing still had an ASR hypothesis with six word errors, and Chatterbox default lecture had three. Short isolated source-clock-free snippets do **not** certify two-hour output stability, prosody continuity, pause placement, A4 singing preservation, source-term semantic faithfulness or final Overdub mix.

## Product architectural decision and one next action

**Owner-selected research winner: VoxCPM2 with the Russian female `kseniya` synthetic reference (F).** Keep VoxCPM2 default and Silero `kseniya` as primary A/B controls. For male dubbing, re-test VoxCPM2 + `aidar` against Silero `aidar`, since the same listener rated the male VoxCPM2 lecture lower than the breathing passage. Chatterbox V3 is deprioritized by actual owner ratings despite its previous technical shortlist. Existing product Silero and Qwen settings remain unchanged: this is an **experimental selection**, not a production TTS cutover.

**Next one action**: implement an **opt-in** VoxCPM2 adapter through the existing `TTSEngine` interface, reusing source-speaker to Russian voice-group ownership and **explicit fixed Russian reference assets**, then test a short real A4-reviewed source-video Overdub with true source clock, phrase-level context, source-original audio preservation, and singing examples. Keep Silero/Qwen as available fallbacks and compare the same speaking script with the winner and the Silero female control. Avoid changing the production default until this actual device test is measured.

No GitHub Actions, main merge, or private artifacts published.
