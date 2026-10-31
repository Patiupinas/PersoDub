# A1 research-only automatic pre-annotation: real vocal-instruction minute

**Date:** 2026-10-31. **Status:** executed three-model, selected-media research pilot; **not** independently reviewed A1 gold, not a qualified A4 speech-to-TTS decision model, and not a full-video benchmark.

## Concrete test: genuine instruction-to-humming transition

Primary source: [US Navy Band - Vocal Warm-Up](https://commons.wikimedia.org/wiki/File:Vocal_Warm-Up_-_United_States_Navy_Band.webm). The recording features a spoken explanation and an actual humming exercise. Wikimedia Commons identifies it as a US Navy work in the **public domain**.

The original 8:36 VP9/Opus WebM was **not downloaded**. Instead:

- Public Wikimedia 240p transcode: 13,409,050 bytes. Exact upstream URL: https://upload.wikimedia.org/wikipedia/commons/transcoded/6/6d/Vocal_Warm-Up_-_United_States_Navy_Band.webm/Vocal_Warm-Up_-_United_States_Navy_Band.webm.240p.vp9.webm
- HTTP GET Range **0-3,000,000** fetched exactly **3,000,001 bytes**, HTTP 206 and \`Content-Range: bytes 0-3000000/13409050\`. Local partial stream SHA-256: \`57cfb5325c68776ebe1edab6217837e7640a26b2d414fc2e1266e6d87e03445b\`.
- Decoded the first two minute intervals separately as **16 kHz mono PCM16**, 60.000 s each. The important second minute is 1:00-2:00, WAV SHA256 \`d409c8994bf9aa05e05e1ba1ec6bfde34224c9136bbc9afc43\`, audio-only 960,000 PCM frames, **raw PCM SHA256 \`4a9ace7fac700764c74cd3215f4b57c5db7fe2ca04bc5f33d68f9b9c80df9e36\`**.
- Upstream original video and original 48 kHz Opus stream have not been independently SHA-frozen. All candidate timestamps below refer to the **selected 240p derivative, 16 kHz mono** and have a +60 s source-offset mapping, not A0-certified original-video frame alignment.
- All actual media/PCM remain only in a temporary directory on the user's authorized Mac; no audio, lyric text, image or model weight appears in Git.

## Three real automatically computed observations

| Model | Download or reuse | Observed output in the second minute |
| --- | --- | --- |
| [OpenAI Whisper Small](https://github.com/openai/whisper) | Reused existing Mac checkpoint SHA \`9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794\`; no ASR model download | **92 word intervals**. Speaker explains posture/breathing, instructs listeners to begin humming on an M sound and go down a scale; a ~25 s demonstration has very little transcribed speech; explanations resume at ~1:45. The raw ASR text remains on the Mac. |
| [SMAD CRNN](https://huggingface.co/duclvQ/smad) | Only **3,342,832-byte** checkpoint SHA \`63818291e401ca27616cb29ba3a224b780296ac4af87e6d6b70edb9daa40f5bc\` fetched; commit \`157a6316366bcf8831baf23df742edb71f07eb47\` | Distinguishes \`speech_noise\`, \`speech_music\`, \`singing_music\`, \`none\` with one-second projected labels from four-second receptive windows. Flagged **1:20-1:28** and **1:39-1:44** as singing over music, but **1:28-1:39** as no voice. |
| [inaSpeechSegmenter 0.8.0 SMN](https://github.com/ina-foss/inaSpeechSegmenter) | Reused previously verified local model file SHA \`f04b5e3c86fa2e81666d106b0867350fe7858c7bd006c2a74c27b5b45507e7d8\` | Labels music continuously from approximately **1:14.88 to 1:45.84**, with speech near 1:10-1:14.88 and again from ~1:45.84 onward. It does **not** identify whether the musical interval contains singing or instrumental music. |

All times are **model output**, not manually established demonstration start/end. The two acoustic models are from different families but also have different target label semantics. Whisper word recognition is an observation of text, not a proof of spoken instructional intent.

## Selected automatic pre-annotation output

Pure research helper [\`app/vocal_annotation_candidates.py\`](../app/vocal_annotation_candidates.py) consumes **only source-clock integer sample intervals**. It does not import Whisper, SMAD or INA model runtimes. Input evidence and output suggestions are committed as **numeric JSON without transcript words**:

- [\`navy-observations-numeric.json\`](vocal-instruction-pilot/navy-observations-numeric.json): **60** SMAD one-second labels, **9** INA original acoustic intervals, **92** ASR word intervals, source offsets and model SHA256
- [\`navy-auto-suggestions.json\`](vocal-instruction-pilot/navy-auto-suggestions.json): the first **8 source-clock contiguous candidate intervals**, model evidence, source PCM derivation, and aggregation

The helper marks any detector boundary neighborhood **±2 seconds** as \`uncertain\`. It labels \`vocal_demo_candidate\` only when SMAD says \`singing_music\` **and** INA says \`music\` away from boundaries; \`speech_candidate\` requires two distinct speech observations and word timing; \`non_target_candidate\` requires no-energy plus no-voice with no words. Disagreement, coverage gaps, ambiguous humming/exercise pauses and changing labels remain \`uncertain\`. This is **proposal generation**, not an independent semantic classifier and not the canonical A1 \`explanation/vocal_demo/non_target\` gold schema.

| Candidate for source time | Machine-prelabel |
| --- | --- |
| **1:00-1:03** | speech_candidate |
| **1:03-1:22** | uncertain |
| **1:22-1:26** | vocal_demo_candidate |
| **1:26-1:41** | uncertain |
| **1:41-1:42** | vocal_demo_candidate |
| **1:42-1:48** | uncertain |
| **1:48-1:59** | speech_candidate |
| **1:59-2:00** | uncertain |

**Aggregate:** 14.0 seconds speech candidates, 5.0 seconds overt vocal-demo candidates, **41.0 seconds uncertain**. This conservatism is real and is not masked as a successful classification score. Speech under piano, humming breaks, breath exercises and demonstration onset/release require better evidence; this sample contains such ambiguity.

The result is **replayable offline** without the models or media: \`tests/test_vocal_instruction_auto_snapshot.py\` recomputes all eight proposed intervals from the numeric frozen model observations and compares sample numbers and evidence roles exactly. No train/test parameter fitting or human listening-based gold confirmation was performed.

## Models to evaluate next for the ambiguous spans only

For this application, time localization and *acoustic meaning* matter more than a model's generic ASR score:

1. **[MOSS-Audio-4B-Instruct](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-4B-Instruct)** supports audio understanding, speech captioning, music context and time-aware questions. Author checkpoint total is **10,445,749,784 bytes**; a separate [community GGUF Q4](https://huggingface.co/cstr/MOSS-Audio-4B-Instruct-GGUF) is approximately **4,111,365,280 bytes** in live HF metadata (both untested in PersoDub). Apache-2.0 model license; infer compatibility and quality on Apple Silicon before introducing a production dependency.
2. **[TEMPO](https://github.com/kaousheik-26/tempo)** is explicitly trained for interval localization/dense audio captions and emits times at **0.1-second resolution** on up to 60-second windows. [RL checkpoint](https://huggingface.co/Kaousheik/tempo-rl-multitask) requires about **16,543,476,655 bytes** including its \`time_proj.pt\`. It is based on Audio Flamingo 3 with research-use terms, and its Apple Silicon execution **has not been verified**. It is a higher-cost reference candidate, not the first default.
3. **[SpotSound](https://huggingface.co/Loie/SpotSound)** is another natural-language event-localization model requiring base Audio Flamingo 3 plus its adapter. Also **unexecuted** here. Its target-event focus is useful for asking "where does an instructor sustain a vowel?", while a broad generic sound caption may miss the short event.
4. **Current small-model stack** is already executable and cheap. Use its high-confidence unreviewed prelabels to prioritize a few seconds for higher-level audio semantics, **rather than downloading entire 60GB visual datasets or all 8 MAVC100 backups**.

**Recommended next protocol:** On the same single Navy minute, apply exactly one time-aware audio-language model to the **uncertain spans**, request typed event intervals and reasoned categories without synthetic phrases, then score its changes *against an independently reviewed A1 event partition*. A1 human labels cannot be generated by feeding the model's own answers back in as gold. After the split and quality gate, adapt the accepted *proposal* interface into the canonical A1 annotation review workflow; A4 remains the only decision owner and original PCM protection invariant remains unchanged.

## Verification

- Mac Python 3.11, pinned Ruff 0.16.6; model-only \`vocal_annotation_candidates\` and its synthetic tests plus frozen real source snapshot. Focused tests and broad local repo suite are run as available.
- No GitHub Actions. Neither model weights nor complete source video were fetched by this experiment, except for the specifically selected **3.34 MB SMAD weight file**. The complete source video is not stored in the project.
- **Current limitation:** 41 s uncertain; one one-minute pilot without human gold is evidence that candidate generation functions, **not** evidence of safe automatic dubbing readiness.
