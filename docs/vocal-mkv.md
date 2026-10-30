# Multi-track Matroska master for selective dubbing (A7)

This helper extends the existing FFmpeg-based media layer with a narrowly
scoped output operation. It does **not** replace PersoDub's `app/media.py`
MP4 mux, `app/subtitle_ass.py` or the existing PCM assembler. It expects a
**completed** dubbed PCM WAV plus three **already generated** subtitle files.

```python
from app.vocal_mkv import build_master, inspect_master

build_master(source_video="lecture.mp4", dubbed_pcm_wav="dubbed-master.wav",
             source_srt="source.srt", russian_srt="ru.srt",
             bilingual_ass="dual.ass", output_mkv="lecture.ru.mkv",
             source_language="de")
```

The output has one original video stream-copy, default Russian FLAC audio,
an independent original audio stream-copy, original-language SRT, Russian
SRT and bilingual ASS. `source_language`: `en`, `de`, `es` or `mul`
(mixed). No subtitles are burned into video.

Input files remain unchanged. Output is written to a temporary MKV file in
the destination folder, verified with ffprobe and atomically published.
Existing outputs are never overwritten. Incompatible original codecs fail
explicitly rather than silently re-encoding the original audio or video.

`inspect_master` checks exact stream counts, language metadata, defaults and
subtitle codecs. Real-FFmpeg synthetic tests generate independent original and
dub WAV files, decode **both** output audio tracks back to PCM, verify byte
equality, and verify that the protected tail survives unchanged.

This proves the mux/codec path only. It does **not** prove vocal-event
detection, accuracy of transitions or prosody. Source PTS, nonzero stream
offsets, long-file performance and cross-platform playback require separate
full-video pilots. This first version stream-copies the first original audio
track only; explicit multiple-source-track selection is future work.

Run `python -m pytest tests/test_vocal_mkv.py -q`. Real media tests skip if
ffmpeg/ffprobe are not installed.
