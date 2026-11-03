# PCM assembly for selective vocal dubbing (model-free prototype)

**Status:** experimental module. Not wired into the standard PersoDub UI or pipeline. Depends on the opt-in [decision schema](vocal-decisions.md) from draft PR #1. No neural models are downloaded or called.

## Safety contract

- All boundaries are **absolute integer decoded PCM frame indices**, including both channels in one frame. No source timestamps are inferred or rounded in the mixer.
- The source must be an **uncompressed PCM16 WAV**, either mono or stereo. `pcm_sha256` in the decision manifest must equal SHA-256 over the concatenated decoded **PCM frame bytes**, *not* the WAV file/header. The manifest `sample_rate` and `total_samples` must match the source file.
- `TRANSLATE`: requires exactly one prepared, matching-format TTS WAV per leaf span. The TTS may be shorter than the slot; the remainder is **digital silence**. The TTS may **not** overrun its time slot. The source-language audio in that slot is not blended into the translated speech. No pitch correction, time stretching, gain changes, fading or source separation occurs.
- `PRESERVE` and `REVIEW`: copied **byte-for-byte** from the original decoded PCM. No TTS is accepted for these spans. Original music/room sound also remains unchanged, including if it overlaps a vocal exercise.
- Uncovered time, overlapping windows, missing TTS, extra TTS, corrupt WAV, invalid hash/format/rate and duration mismatch reject the entire output. Failure does **not** overwrite a previously existing output.
- Input audio is read in bounded chunks (65,536 PCM frames). The source PCM hash is checked **before and during** assembly. The temporary WAV is independently compared with source PCM on every protected span before being atomically published using `os.replace`.
- The output contains exactly the same number of frames as the source. Results report the number of source-backed/translated frames and raw PCM SHA-256 of the output.

## Usage

1. Prepare one decoded PCM16 WAV (`source.wav`) and a schema-v1 `decisions.json` with its correct raw PCM SHA-256, sample rate and frame count.
2. For each `TRANSLATE` leaf segment, prepare a mono/stereo PCM16 WAV matching the source layout and sample rate. The file must be **no longer** than the interval assigned to it.
3. Assemble the source and replacements:

```bash
python -m app.vocal_pcm \
  --source source.wav \
  --decisions decisions.json \
  --tts speech-1=speech-1.ru.wav \
  --tts speech-2=speech-2.ru.wav \
  --output dubbed.ru.wav
```

The command prints a small JSON summary and exits `2` if data or integrity validation fails. Use `verify_preserved_wav` to check a WAV produced by another assembler against the same manifest:

```python
import json
from app.vocal_pcm import verify_preserved_wav

with open("decisions.json", encoding="utf-8") as fh:
    decisions = json.load(fh)

protected_frames = verify_preserved_wav("source.wav", "dubbed.ru.wav", decisions)
print(f"Unchanged original PCM frames: {protected_frames}")
```

## Synthetic tests

```bash
python -m pytest tests/test_vocal_decisions.py tests/test_vocal_pcm.py -q
```

The tests produce short WAVs via Python `wave` and `struct` in temporary folders. They include `speech -> sustained vowel -> speech -> uncertain transition`, sample boundaries across read chunks, mono/stereo, 44.1/48 kHz, omitted or overlong TTS, SHA mismatch, corrupt input, unchanged output on failure, and intentional corruption of a supposedly preserved segment. They do not require FFmpeg, network access, a model server, video files or a GPU.

## Limitations / next integration tasks

- **No background bed** on `TRANSLATE`: the prototype produces TTS over silence. Production mixing can use PersoDub's existing separated *background* on translated windows, but must not reconstruct protected spans from vocal stems; protected intervals always use original decoded PCM.
- **Hard segment edges**: no crossfades; the prototype proves exact PCM preservation first. Before real use, evaluate clicks and transitions and apply any fade **only inside the permitted translated interval**, not across a protected attack or decay.
- **TTS duration is the caller's responsibility**. A too-long take is rejected; a shorter take is zero-padded. Automatic retranslation, duration fitting and speaker-reference selection remain outside this module.
- **RIFF/WAV PCM16 only**: not RF64, float WAV, WAVE64, mp3 or AAC. RIFF size limits constrain extremely long outputs; use a container-capable streaming backend if needed after the pilot.
- The `source_sha256` identifies the original imported container and is only **syntax-validated** by PR #1. Ingest must verify the actual container hash and establish exact original video PTS -> decoded PCM frame mapping. This prototype verifies `pcm_sha256` against the provided decoded WAV.
- A perfect match on PCM-preserved regions **before** lossy encoding does not imply AAC/MP4 will retain bit-identical samples. Post-encoding audible quality and time synchronization require separate tests.
- The system **does not yet detect** singing, exercises, growls, breathing, mixed windows or speaker changes. A wrong decision can still alter the wrong audio. A conservative decision engine and independent gold annotations must be added before running on real lectures.
- This is an *offline local experiment*, not finished selective dubbing. The original PersoDub pipeline is untouched.
