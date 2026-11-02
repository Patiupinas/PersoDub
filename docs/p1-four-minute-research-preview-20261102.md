# PersoDub P1: source-exact 234.684 s RU research playback

**Status:** OBSERVED_RESEARCH_PREVIEW_NOT_A4_APPROVED. This is an experimental listening artifact, not released dubbing or evidence of native Russian voice quality.

## Source and why a new full-length mix was needed

- Original *Breath Control for TOTAL Beginners* from the user's local job, SHA-256 `27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322`. Its original video is 234.633 s; original AAC is 234.684082 s.
- Corrected bounded-source English SRT is independently regenerated Faster-Whisper Large-v3 with 647 owned words and no collapsed word times, **not independent human English transcript gold**.
- Existing 34 s source snippet was decoded through a different FFmpeg extraction path. Its PCM was **not byte-identical** to the 145-179 s slice of a newly decoded full 48 kHz original. Splicing that complete previously mixed snippet would modify protected original samples. Instead, the new research runner starts from the entire source PCM and mixes only existing per-line synthetic RU WAVs at source-aligned frame indices.
- Each synthetic voice is time-bound to its source slot with raised-cosine fades wholly inside the experimental speech interval. The original PCM elsewhere is asserted exactly identical in `splice_unapproved_pcm`. All speech/exercise intervals without research audio are untouched, not automatically classified.
- The original application job and original input are unchanged. No A4 actions were approved or modified.

## Implemented research tools

- `benchmarks.persodub.research_full_preview`: opt-in command for the pinned real video. Validates source SHA, source-clock WAV, unapproved frozen 145-179 s speech manifest, per-line WAV sample rate/duration/overlap, and optional additional corrected-source SRT SHA-bound research manifest. Produces full-length PCM, a two-selectable-audio-stream MP4 via existing `media.mux_overdub`, and a receipt. This does **not** replace the production A4 decision engine.
- `benchmarks.persodub.research_subtitle_mux`: optional two subtitle streams (corrected-source EN SRT and only those RU phrases synthesized for this unapproved experiment), stream-copying video plus two audio streams.
- Both scripts refuse overwriting output. Additional experimental RU utterances with `OVERRUN_NOT_USED` stay original rather than being truncated and misrepresented as successful speech. The new source-bound Russian text and TTS WAVs are in private Mac reports, not Git.

## Exact first real outputs (2026-11-02)

From the already cached five Qwen3-TTS Russian clips for original source 145-179 s, two full 234.684 s candidates were rendered:

| Variant | Research speech | Exact untouched source PCM | Alternate soundtrack |
| --- | ---: | ---: | --- |
| timbre (5 clips) | 18.48 s | 216.204 s | Qwen cloned from earlier SPK0 reference |
| clean-ICL (3 of 5 clips, two timbre reused) | 19.12 s | 215.564 s | ICL with a speech-dominant clean reference |

Both 2-audio MP4s were verified to contain **7,039/7,039 byte-identical video packet hashes** and **10,107/10,107 byte-identical original AAC packet hashes**. These comparisons are saved privately in `packet-validation-timbre.json` and `packet-validation-clean-icl.json`. `breath-control-234s-timbre-bilingual-preview.mp4` additionally contains separately selectable English and Russian subtitle tracks (the RU track is only five draft cues, not a full lesson translation).

**Files on Raymonds-Laptop.local:**

`~/Documents/PersoDub-Research/reports/p1-full-lesson-research-20261102/`

The exact original PCM sha, output WAV/MP4 sha, frame clock, synthetic clip origins and incomplete human-quality assertions are in individual private receipts. Never infer speaker similarity or natural RU pronunciation from equal streams or ASR readability.

## Expanded corrected-source synthesis experiment

A separate **19-utterance, unapproved AI-authored Russian draft** was prepared against the corrected English source SRT, with explicit source start/end, conservative exclusion of ambiguous vocal demonstrations, and the original video SHA. It uses locally cached Qwen3-TTS-1.7B Base on Mac MPS and a speech-dominant 6.56 s source voice sample. Per-utterance files, private text, deterministic seeds, source identity and duration results are stored outside Git. If an initial generated line overruns, it is marked `OVERRUN_NOT_USED`; a separate shorter *meaning-preserving proposal* is available for a new TTS pass. No model-inferred A4 approval follows from this work.

Final counts and whether this extended variant provides acceptable Russian voice are **NOT_RUN** until the new inference, external ASR readback, source packet comparison and human listener evaluation complete.

## Reproduction / next experiment

On the Mac, with the pinned original video, frozen research manifests and cached WAVs:

```sh
python -m benchmarks.persodub.research_full_preview --video /private/original/input.mp4 --source-wav /private/full/source-original-48k.wav --manifest /private/34s/qwen-ru-research-manifest.json --voice-root /private/34s --variant timbre --output-wav /private/full/replay.wav --output-mp4 /private/full/replay.mp4 --receipt /private/full/replay.json
```

The official `app.vocal_overdub_export` remains the **only product A4-approved route**. The next hard product-quality gate is true human source speech/exercise boundaries, corrected Russian adequacy, native-Russian blind voice ratings and timing on the full four minutes. Do not merge this research output into the product default or publish private audio/video/dataset files.
