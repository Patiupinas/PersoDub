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

## Subsequent exact-source 24-clip result (Mac, 2026-11-02/03)

The completed local Qwen3-TTS research re-synthesis generated 19 additional AI-authored Russian **speech-only** drafts from the corrected bounded-source English SRT, using the previously saved 6.56 s speech-dominant SPK0 reference. First passes fit 14/19 source slots, then **shorter Russian phrasing** plus selected retakes produced 19/19 fitting WAVs. The earlier 5 frozen 145-179s drafts were combined with them: final total **24 Russian clips, 112.56 s of active synthesized voice**. Private manifests include per-file SHA, text, voice seed, slot, A4 NOT_APPROVED and review flags. None of these draft translations is independent bilingual gold.

**Measured source-clock defect and repair:** the initial 34-second research manifest placed case `d` at 168.36 s despite source English speech starting 169.36 s. The research mixer now takes the maximum of the candidate and source onset and caps it by the source end. The prior timbre clip (3.12 s) no longer fits the true 169.36-171.60 s source interval; the previously cached 2.08 s clean-reference ICL clip fits there, so the final 24-clip mix uses that real existing take. The same source-clock constraint applies to bilingual captions. Subtitle cue timestamps in the verified final variant are taken from the **actual PCM placement receipt** (SHA-bound to the exact two-audio MP4), not an obsolete timbre duration in the draft manifest.

**Final preferred listening artifact** on Raymonds-Laptop.local:

`~/Documents/PersoDub-Research/reports/p1-full-lesson-research-20261102/breath-control-234s-corrected-24-verified-bilingual.mp4`

This MP4 contains source video, selectable **Overdub** and byte-identical AAC **Original** audio streams, and 74 English and 24 Russian text cues as separately selectable subtitle streams. The video is still only **partially dubbed**: demonstrations, pauses, uncertain source intervals and other material outside the 24 approved-for-**research-only** speech clip windows keep their original English audio.

The entire original decoded PCM outside 24 selected synthesis windows is **exactly unchanged** across **5,861,956 frames (122.124083 s)**; the remaining **5,402,880 frames (112.56 s)** receive translated-voice mixing. The full source has **11,264,836 frames (234.684083 s)**. Independent FFprobe packet-data SHA comparisons to original prove **7,039/7,039 video packets** and **10,107/10,107 original AAC packets** identical, even in the final five-stream bilingual export. Local receipt and verification:

- `breath-control-234s-corrected-24-voice.json`
- `final-24-verified-technical-validation.json`
- `final-24-ru-caption-clock-validation.json` (all 24 Russian subtitles were extracted from the final MP4 and compared against the actual placed PCM frames; **maximum timing error 0.000 seconds** on the millisecond subtitle clock)
- `full-lesson-ru-independent-asr.json` (independent recognizer's raw words/metrics; private)

The preserved original PCM and compressed packet checks establish **technical pass for this frozen source only**. They are not human semantic, A4, speaker likeness or singing boundary gold.

Independent local **Faster-Whisper Large-v3 CPU int8** readback of all 24 RU clips against their *TTS target text*, not source-language meaning, returned **7 edit errors / 232 reference words = WER 0.030172 (3.0172%)**; five target lines had nonzero errors. Report: `full-lesson-ru-independent-asr.json`. Recognizability is not a native accent, voice similarity, correct translation or preserved-pause MOS assessment. Human native-RU panel scores and complete mixed speech/exercise A4 source boundaries still **NOT_RUN**.

No fresh weights/downloads, no training, no Github Actions or main/default product cutover. The isolated Qwen MPS HTTP sidecar was stopped after inference, leaving no active TTS server. Older 5-clip and 23-clip research MP4s remain diagnostic historical outputs and have **not** received the corrected source onset or the final exact subtitle-placement timing.

**One next action:** use existing A4 UI on the original source to approve source speech/exercise boundaries, then conduct a genuine native-RU blinded voice/pause/translation adequacy review against this 24-clip private variant. Keep source media and translated text private until human quality is verified.
