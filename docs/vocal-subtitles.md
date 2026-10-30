# Selective source/Russian/bilingual subtitle tracks (A5)

The small `app/vocal_subtitles.py` layer **reuses** PersoDub
`app.text.srt.build_srt` and `app.subtitle_ass.build_ass`. It does not
implement a new subtitle formatting engine. No OCR/ASR/translation or TTS
is performed.

Input: approved **leaf** decisions with `id`, `start_sample`,
`end_sample`, `action`, `source_text`, `ru_text`.
Only `TRANSLATE` speech is emitted. `PRESERVE` vocal and `REVIEW`
content is intentionally not fabricated as a spoken caption;
a later manually verified caption mode would require an explicit contract.
`MIXED` parents must be resolved upstream to leaf decisions.

```python
from app.vocal_subtitles import build_subtitle_tracks

output = build_subtitle_tracks(approved_segments,
                               sample_rate=48000,
                               width=1920,
                               height=1080)
# Write the three returned texts as source.srt, ru.srt and dual.ass.
```

Results contain `source_srt`, `russian_srt`, `bilingual_ass`,
`translated_cues`, `protected_cues_skipped`. A7's
`app.vocal_mkv.build_master` then packages these subtitle files with
finished audio and video. Subtitle rendering is a pure function; the
orchestrating layer owns actual file writes. Supports source language
independently of wording (DE/EN today; ES planned).

Tests reject invalid actions, duplicate IDs, reversed/overlapping
speech subtitle spans and missing RU text; source and RU timings must match.
Full end-to-end video integration is deferred to A0. No changes to
PersoDub's standard MP4/ASS export behavior.
