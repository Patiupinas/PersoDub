# Multi-track Matroska master for selective dubbing (A7)

This helper extends PersoDub's FFmpeg media layer with a narrow final
export operation. It does not replace `app/media.py` or the existing PCM
assembler and does not perform TTS or subtitle authoring.

Inputs: source video (including original audio), completed 48 kHz / 16-bit
dubbed PCM WAV, original SRT, Russian SRT, and bilingual ASS.

```python
from app.vocal_mkv import build_master, inspect_master

build_master(source_video="lecture.mp4", dubbed_pcm_wav="dubbed-master.wav",
             source_srt="source.srt", russian_srt="ru.srt",
             bilingual_ass="dual.ass", output_mkv="lecture.ru.mkv",
             source_language="de")
```

Stream map: original video **stream-copy**; Russian dubbed audio encoded
to 16-bit lossless FLAC (default); original audio **decoded and encoded
to 16-bit lossless FLAC**, preserving the sample sequence as played from
the source; original SRT, Russian SRT, and bilingual ASS as soft subtitle
tracks. Source language is one of `en`, `de`, `es`, `mul`.

**Why original audio is FLAC rather than AAC stream-copy:** a real local
MP4/AAC test showed that copying AAC from MP4 to MKV exposed different
decoder priming samples. Encoding the *decoded source samples* to
`-sample_fmt s16 -c:a flac` produced exactly the same decoded PCM
as the source MP4. Using 16-bit explicitly avoids the round-trip
quantization change observed with FFmpeg's default 24-bit FLAC output
for decoded floating-point AAC. The target canonical audio contract
uses 16-bit PCM; higher-bit-depth sources require a separate policy.

`inspect_master` validates stream counts, language tags, dispositions,
16-bit FLAC for **both** audio tracks and SRT/SRT/ASS formats. FFmpeg
synthetic tests verify exact decoded PCM identity for both tracks and
protected intervals. A separate MP4/AAC integration test verifies
source-decoded PCM identity after remux/transcode.

Output uses a temporary MKV file in the destination folder, verifies
streams, then atomically publishes. Existing files are never overwritten.
This initial profile preserves the **first** original audio track only.
No video re-encoding, subtitle burn-in or default PersoDub export changes.

A7 does not classify vocal sound or measure prosody. Source PTS with
nonzero start offsets, multitrack source selection and long-video
performance still require full-video pilot evidence.

Run `python -m pytest tests/test_vocal_mkv.py -q`; real media tests
skip if ffmpeg and ffprobe are unavailable.
