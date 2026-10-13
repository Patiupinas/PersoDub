# Known limitations & roadmap

[← Back to README](../README.md)

## Known limitations

- **Emotional delivery is weaker than the original.** Timbre is cloned faithfully, but
  intense emotional performance does not fully carry over.
- **Diarization can slip when speakers sound alike.** Similar voices may be merged or
  swapped, particularly in crowded scenes.
- **Without a GPU, long videos dubbed on this computer are impractical.** Everything
  still runs, but voice synthesis (and a local translator) falls back to the processor
  and slows down sharply — see
  [Speed without a GPU](faq.md#speed-without-a-gpu). Short clips remain fine.
- **Linux is not supported yet.** macOS (Apple Silicon) and Windows are supported.
- **The voice-leak check can leave some leaks.** On a dub made on this computer it is on
  by default: it measures whether original speech bleeds through beneath the dub and
  cancels what it finds. When some still fails the check, it delivers the cleaned mix
  with a warning in the job log, so listen before you publish.

## Roadmap

Planned, in no committed order:

- **Additional platforms** — a Linux desktop build
- Stronger emotional delivery in synthesized speech
- More reliable diarization when speakers sound alike

Have a use case that is not covered? Open an
[issue](https://github.com/stronghamjji/PersoDub/issues) — it helps set priorities.
