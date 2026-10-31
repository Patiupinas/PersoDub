# A1 semantic review: MOSS-Audio on genuine vocal-instruction audio

**Date:** 2026-10-31. **Result:** executed local Apple Silicon/Metal inference, reproducible numeric record, negative qualification for automatic decisions. **Status:** unreviewed machine *window-level* evidence, not human A1 gold, not acoustic-accuracy data, and not a policy-to-TTS integration.

## Question and controlled scope

Can an audio-language model disambiguate the **41 seconds of REVIEW-like uncertainty** found in the existing Navy vocal instruction minute of [A1 PR #21](https://github.com/Patiupinas/PersoDub/pull/21), without confusing spoken explanation with demonstration?

Only the pre-existing 60-120 s decoded excerpt from the [public-domain US Navy Band Vocal Warm-Up](https://commons.wikimedia.org/wiki/File:Vocal_Warm-Up_-_United_States_Navy_Band.webm) was used. No additional video or audio was fetched. The source WAV is 16 kHz mono PCM16 SHA-256 `d409c8994bf9aa05e05e1ba1ec6bfde9e19e000ad33de34224c9136bbc9afc43`; decoded PCM SHA `4a9ace7fac700764c74cd3215f4b57c5db7fe2ca04bc5f33d68f9b9c80df9e36`.

- **Five whole A1 windows:** 3 uncertain windows covering 40 of 41 uncertain seconds (1:03-1:22, 1:26-1:41, 1:42-1:48); 2 acoustic controls (1:22-1:26 vocal candidate and 1:48-1:59 speech candidate). The remaining 1:59-2:00 uncertain tail was not queried.
- **Five nested diagnostic windows:** 1:03-1:06, 1:10-1:15, 1:16-1:22, 1:28-1:35, 1:46-1:48. These overlap the parent windows deliberately; they are not an additional independent test set.
- Every crop is made from the already-decoded 60-second PCM by frame slicing, **without resampling**. Absolute sample positions reference this derivative plus its 60-second offset, not an independently PTS-verified original video stream.
- No human adjudication was performed. Previous INA/SMAD/Whisper observations are **not** human gold.

## Runtime and model

One local model, no alternatives downloaded:

- **MOSS-Audio-4B-Instruct**, community `Q4_K` GGUF from [cstr/MOSS-Audio-4B-Instruct-GGUF](https://huggingface.co/cstr/MOSS-Audio-4B-Instruct-GGUF), pinned repository revision `d4bb0c6450f6931adeb6a0fe79bdee9857285e39`; exact downloaded weight file **4,111,365,280 bytes**, SHA-256 `7f2fd36c357a39c17a26937b5a726f86f55484c53bb819a7e0706c2f92e7cc90`.
- [CrispASR](https://github.com/CrispStrobe/CrispASR) prebuilt macOS ARM64 **v0.8.49**, commit `d9426437`, release archive SHA-256 `53fa0b1addeacaafd05f8b0cd10cad6e8f44cbe302be3bd07fdf7fce2eff27ec`. Metal backend, Apple M1 Max with 64 GiB unified RAM, 4 CPU threads, `-l en`, `-n 140`, default temperature 0.
- Three frozen exact prompt texts and SHA-256s appear in [moss-window-observations.json](moss-window-observations.json): **lesson** (vocal-course framing), **neutral** (no assumed context and a different label vocabulary), **alt_context** (same wording and label taxonomy as lesson except the opening sentence, replaced with unknown purpose).
- The model/release archive and the source audio stay local on the Mac; no model weights, media, original transcript, or freeform model text are checked into Git.
- The CrispASR MOSS backend returns **one response for the whole clip**. It does not provide verified word- or event-level sample boundaries in this adapter.

## Real observations, not model accuracy

Across all **10 identical audio windows** classified with both lesson and neutral prompts, 4 of 10 **changed normalized class**. This comparison changes some category definitions in addition to instruction wording, so it is a broad prompt-formulation experiment, not a one-variable causal test.

With a stricter comparison (same label taxonomy and instructions, changing only the opening context sentence), **4 of 6 windows changed class**.

| Original derivative source time | Lesson prompt | Neutral prompt | Changed-opening-only prompt |
| --- | --- | --- | --- |
| 1:22-1:26 control | vocal | vocal | **non_target** |
| 1:48-1:59 control | speech | speech | speech |
| 1:03-1:22 uncertain | vocal | **speech** | vocal |
| 1:26-1:41 uncertain | vocal | vocal | Not run |
| 1:42-1:48 uncertain | vocal | **speech** | **non_target** |
| 1:03-1:06 probe | speech | speech | Not run |
| 1:10-1:15 probe | vocal | **speech** | **speech** |
| 1:16-1:22 probe | vocal | **speech** | **non_target** |
| 1:28-1:35 probe | vocal | vocal | Not run |
| 1:46-1:48 probe | speech | speech | Not run |

Crucial specific contradiction: On **1:10-1:15**, Whisper Small emitted ordinary spoken words, while SMAD labeled most of the interval `speech_noise` and INA also reported speech near 1:10-1:14.88. The lesson-context MOSS prompt nonetheless said `VOCAL_DEMO`. This is a **cross-model conflict**, not proof that any one model is correct without independent listening review.

Changing only the introductory context sentence made the **1:22-1:26 acoustic vocal control** change from `VOCAL_DEMO` to `NON_TARGET (no human voice)`. In three repeated identical-prompt/identical-source checks, the raw output SHA matched byte-for-byte (3/3). The observed prompt-conditioned differences were reproducible on this runtime, not transient decoding changes in these repeated checks.

Wall-clock runtime was 10.159 seconds for the initial 4-second cold run and around 2.6-4.4 seconds per later selected crop (2-19 seconds of input), including model startup where applicable. These are bounded local measurements, not product performance guarantees.

## Integration decision

**Do not count MOSS-Audio as a second independent A4 speech vote, do not alter the existing A4 policy, and do not automatically change any A1 `uncertain` seconds to `TRANSLATE` or `PRESERVE`.** A prompt pair agreeing on a class is not ground truth and not an independent detector.

Useful reuse is limited to **optional A1 review hints**, with explicit model/prompt/source hashes and a disagreement indicator. The deterministic stdlib-only [audit module](../../app/vocal_semantic_review.py) checks provenance shape, source clock, category mappings, different prompt outcomes, and repeat hashes; it emits **no actions, event partitions, subtitles or new gold labels**.

The most efficient next qualification step is a human-reviewed EN/DE vocal-technique A1 reference, plus source-clock text/acoustic boundaries from existing A3 and A2. Validate a model/runtime against those labels before deciding whether to implement a semantic backend in PersoDub. If exploring this exact MOSS model further, distinguish the reference Hugging Face implementation from this particular Q4_K/CrispASR runtime; this experiment cannot attribute its behavior to the upstream model, quantization, or runtime individually.

## Offline validation

The checked-in JSON contains **numeric/categorical results, clip WAV SHA, prompt text/hash and model/runtime identity**. It excludes model bytes, media and raw transcripts. It is replayable without Hugging Face or CrispASR:

```sh
python -m pytest tests/test_vocal_semantic_review.py -q
```

This verifies the frozen observation contract and compares recorded responses. It is **not fresh inference**, not a blind trial, and not a quality score. The same audio windows are used for all prompt comparisons, and nested clips must not be counted as independent human examples.

GitHub Actions are not enabled, no PRs are merged, and the production PersoDub pipeline and WhisperNotes are unchanged.
