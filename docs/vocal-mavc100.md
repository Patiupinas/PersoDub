# MAVC100: selective video benchmark and source-disjoint label audit

Status: model-independent **real annotation and real media preflight**, 2026-10-30. The three selected 30-second source videos were downloaded **only via HTTP byte ranges** into an isolated temporary directory on the connected Apple Silicon Mac. No full 8-part video archive was downloaded; no audio/video is committed to Git.

Upstream: [MAVC100 video and frame-level labels](https://github.com/Yuanbo2020/Audio-Visual-VAD/tree/main/Open_dataset_MAVC100), Hou et al. ICASSP 2021. The original dataset authors state **research use only** for backup performance videos and their own annotations. Our code has no runtime dependency on MAVC100, INA or WhisperNotes.

## Annotations read on the Mac

Only the **audio-label** archive was fetched first: \`Frame_level_audio_labels.rar\`, **52,122 bytes**, SHA-256 \`325eecf30f3cb1c457c3c027a91e928b58ba286a15944f34210900131f0c9a49\`. The existing native \`bsdtar\` extracted 200 small TSV-like \`.csv\` files (about 800 KB total).

The published format is UTF-8 BOM / tab-delimited Adobe-like cue rows (\`Name / Start / Duration / Time Format / Type / Description\`), with \`1s/1e\` for speech, \`2s/2e\` for singing, \`3s/3e\` for silence and decimal \`MM:SS.mmm\`. Unlabelled portions are \`Others\`, **not** automatically approved explanatory speech.

\`app/vocal_mavc100.py\` provides a strict, pure standard-library parser and a deterministic, configurable clip selector; no audio/video files are loaded. The selector requires three **consecutive** positive speech/singing/speech events of >=500 ms each and <=3000 ms between neighboring events, uses immutable original source IDs, and keeps all unmodified annotation bytes hashed.

### Exact full-folder result

| Check | Count |
| --- | ---: |
| CSV annotation files | 200 |
| Valid after normalized surrounding marker whitespace | **199** |
| Contains both speech and singing, any positive interval | **65** |
| Contains both speech and singing with >=500 ms of each | **58** |
| Contains strict speech->singing->speech event sequence | **8** |
| Rejected invalid CSVs | **1** |

The one excluded file is \`xiaoxiami_chuangtianya_5.csv\`: at line 7 there is a \`3e\` (end silence) with no preceding \`3s\`; the data is not repaired. Another file has a harmless trailing space on \`2s \`, which is normalized **only for marker parsing**, not in its source bytes or SHA.

### Reproduce annotation-only audit

\`\`\`bash
python -m app.vocal_mavc100 \
  --labels /path/to/extracted/Frame_level_labels_in_audio_streams \
  --output /path/to/new-audit.json \
  --limit 3 \
  --clip Jessie_J_performs_Bang_Bang_5 \
  --clip Ellie_Goulding_performs_Burn_3 \
  --clip Jess_Glynne_performs_123_4
\`\`\`

It rejects existing outputs, invalid marker sequences, overlapping labels, time fields below millisecond precision, unknown requested clips and repeated source IDs. It **does not** infer language, narration, speaker identity, vocal technique, or permission to translate.

## Exactly three source-disjoint 30-second videos

Instead of retrieving 8 RAR backups (~775 MB), the pilot indexed RAR5 metadata with HTTP Range requests, then fetched the **exact compressed byte ranges for three file entries**, reconstructed valid single-member RAR5 files with authentic archive end-header CRCs, extracted with \`bsdtar\`, independently verified video CRC32 against the RAR metadata, FFprobe stream content and SHA-256. Original backups remain on GitHub, not in PersoDub.

| Clip | RAR part | Source video bytes | Source video SHA-256 | Source annotation CSV SHA-256 |
| --- | ---: | ---: | --- | --- |
| \`Ellie_Goulding_performs_Burn_3\` | 3 | 1,898,522 | \`09b51d7cbd4f113c68d5ad6d5ce1a0ef577a0bff0f13e1b83983b5e5d3ba92cb\` | \`937441d61159a7ff069af5e7c89d89f3362d957a337dd65f1cbbbe4d003099a9\` |
| \`Jessie_J_performs_Bang_Bang_5\` | 3 | 6,068,743 | \`e299a5db5bf72caee28e6c00d89decd92f60e0b22e6a86e35281cbd4b89f0a3c\` | \`c0ddf6bdcf5292be61d33cef02fea8a9ff6ffcfe7a8e118e818b0e771128f615\` |
| \`Jess_Glynne_performs_123_4\` | 5 | 7,223,331 | \`dc11f5aedd32545861b268df12f2271439904134ca1a9eb99804f6895df5e056\` | \`ab8917ac896bd42b3e5906129069722c1c5113873428fef4d0af7232f73d5209\` |

These three are manually curated from different named performances and are **not** a model-validated test split. Selection uses exact \`--clip\` allowlisting, not the default top-three ranking, so no other video is downloaded. The native MP4s are H.264 + AAC stereo 44.1 kHz and each has a 30.030 second **container** duration.

## Decoded source PCM evidence and clock nuance

For each video, FFmpeg 9.0.2 successfully decoded the *first audio stream* to raw, stereo, interleaved 16-bit PCM at exactly 48 kHz, streaming output in bounded chunks directly into SHA-256 (no additional PCM files written). Each contains **1,440,000 frames / exactly 30.000 seconds**, and \`ffprobe\` reports audio \`start_time=0.000000\`. Source PCM hashes:

- Ellie: \`a046c96d8b67867ef7ba794abcd1978ff6b8b8cb71fbd92376f3d06e353be769\`
- Jessie: \`687de13bf10f2e5dc8928edf9c5ea3b6f3689864d88002509684c93a3f2051bd\`
- Jess: \`72c623dc5ac72154f0bd3a7fe0e5e521d17cf7df31713ef76d560744cf1563ff\`

**Source clock difference:** the annotation silence \`3e\` can terminate at **30.030 s**, 30 ms (**1,440 PCM frames**) past the decoded audio's 30.000 s, even though labeled speech/singing in selected pilot clips end earlier. Any sample-level scorer must explicitly reconcile the end silence against source audio length; do **not** invent samples or silently treat overrun as prediction failure. Frame-level original labels are not inherently exact sample-level gold and must remain marked as timing observations.

## Verification and remaining gates

- macOS Apple Silicon, Python 3.11: **37 isolated parser tests PASS**, pinned \`ruff==0.16.6\` on changed files **PASS**, real audit applied to **all 200** extracted audio CSVs with results above. Cross-platform repository CI still to be confirmed on the final PR head.
- **Not yet executed:** INA speech/music/noise neural model inference, human listening, model F1/recall, audio-visual labels vs audio labels, real A1 explanation/vocal_demo agreement, translation or video dubbing.
- MAVC100 speech labels include onstage talk and background voices; singing is not necessarily a teacher exercise and unpitched vocal techniques are not exhaustively represented. **No** automatic conversion from dataset \`Speech\` to application \`TRANSLATE\`. The existing A1 gold and A8 scoring contracts remain authoritative for selective-dubbing acceptance.

First execution target: the three verified MP4s above, no more downloads. Run exactly one pinned acoustic baseline, then evaluate its output on the same bounded video list against **only** verified observation labels. Keep separate outcome reports for P2a whole-file and P2b frame-level intervals; avoid claim that these three clips measure all vocal techniques.
