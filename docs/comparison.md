# Where PersoDub fits

[← Back to README](../README.md)

Open-source video dubbing has good options, and they solve different problems. If
PersoDub is not the right fit, one of these probably is:

| Project | License | Shape |
|---|---|---|
| [VideoLingo](https://github.com/Huanshere/VideoLingo) | Apache-2.0 | Subtitle-first pipeline with dubbing, web UI |
| [KrillinAI](https://github.com/krillinai/KrillinAI) | GPL-3.0 | Translation and dubbing with scriptable stages and a CLI |
| [Voice-Pro](https://github.com/abus-aikorea/voice-pro) | GPL-3.0 | Broad voice toolkit — transcription, cloning, separation |
| [VoiceStudio](https://github.com/debpalash/VoiceStudio) | AGPL-3.0 | Local voice cloning and voice design across many languages |

**What PersoDub does differently: it fits the translation, not the audio.** Every other
approach absorbs a length mismatch in the audio. PersoDub absorbs it in the translation
instead: every translator that can follow a length rule is asked to land each line
within ±15% of its subtitle slot. If you have ever noticed a dub subtly sped up to fit
its slot, that is the artifact this project works to avoid. Only a line that would
still run into the next one is played faster, by at most 10% with its pitch kept
(`QWEN_MAX_SPEEDUP`), and whatever is left over is then cut; the job log names each line
that was sped up or cut. This is how dubs made on this computer work; a Perso API dub
is timed by Perso.

**On licensing:** PersoDub is AGPL-3.0, like VoiceStudio. Commercial use is fine; a
changed version that is distributed or run as a service shares its source under the same
license. Releases up to 0.6.5 were Apache-2.0 and stay that way.
