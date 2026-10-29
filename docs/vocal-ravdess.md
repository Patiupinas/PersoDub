# Public RAVDESS speech/song archive index (offline)

**Purpose:** prepare a reliable *file-level* English speech-versus-singing
benchmark without downloading or committing commercial lectures. This is
independent of the sample-accurate selective dubbing decision schema.

**Public source:** [RAVDESS Zenodo record](https://zenodo.org/records/1188976),
Livingstone and Russo, v1.0.0, 2018. The original corpus is publicly
accessible **without requesting individual access** under
**CC BY-NC-SA 4.0**. This allows noncommercial use subject to attribution and
share-alike conditions, not unrestricted commercial reuse.

## Original public archives

| Kind | Direct ZIP download (Zenodo, no login) | Official MD5 | WAV count |
| --- | --- | --- | --- |
| Speech | [Audio_Speech_Actors_01-24.zip](https://zenodo.org/api/records/1188976/files/Audio_Speech_Actors_01-24.zip/content) | `bc696df654c87fed845eb13823edef8a` | 1,440 |
| Singing | [Audio_Song_Actors_01-24.zip](https://zenodo.org/api/records/1188976/files/Audio_Song_Actors_01-24.zip/content) | `5411230427d67a21e18aa4d466e6d1b9` | 1,012 |

Original audio-only recordings are 16-bit 48 kHz WAV. Actors are 01–24; song
recordings exist for 23 actors (actor 18 has no song files).

Download both ZIPs manually to an ignored data directory **outside Git** and
run from the repository root:

```bash
python -m app.vocal_ravdess \
    --speech /data/Audio_Speech_Actors_01-24.zip \
    --song /data/Audio_Song_Actors_01-24.zip \
    --output /data/ravdess-index.json
```

The script reads ZIP metadata and hashes the two ZIP files, compares **MD5 to
Zenodo's published values**, checks exact number of WAVs, validates the
7-field RAVDESS names and actor IDs, then writes JSON containing each file's
voice type, actor ID, emotion/intensity IDs, statement/repetition ID, ZIP
member, compressed metadata, split and archive SHA-256.

It does **not** extract, transcode, or publish audio, call the internet or run
models. Archive hash verification is against the published MD5; the generated
SHA-256 is for our own stronger subsequent provenance checks. Per-file ZIP CRC
is recorded from the central directory but its decompression-based validity
is **not tested** at this stage.

## Speaker-disjoint benchmark splits

Fixed before evaluating a model; do not tune split assignment based on results:

| Split | Actors | Speech files (official corpus) | Song files |
| --- | --- | --- | --- |
| Train | 01–16 | 960 | 704 |
| Dev | 17–20 | 240 | 132 (no actor 18 song) |
| Test | 21–24 | 240 | 176 |

This split prevents the same actor appearing in both training and holdout.
Speech versus song is a **file-level ground-truth label**, not a claim that
every frame in the file is voiced or that a detector's boundaries are safe.

**Do not** convert whole-song/whole-speech labels directly into the project
`TRANSLATE/PRESERVE/REVIEW` sample-accurate benchmark. A real lecture can
contain speech, silence, breath, an isolated vowel, purring, singing, music
and overlapping speech within one file. Those time spans require separate
manual annotations on a held-out speaker/lecture set before acceptance.

## Verification status

- Official links, ZIP filenames, published checksums, filename grammar and
  corpus counts were checked against the Zenodo v1.0.0 page.
- 13 synthetic ZIP/filename tests exercise the parser, stable actor splits,
  checksum failure, malformed channels/actors, duplicate filenames, unsafe
  ZIP paths, incomplete archives and no-overwrite CLI behavior.
- **Real RAVDESS ZIP downloads and parsing have not yet run here.** The script
  remains an experimental corpus-preparation utility until verified on the
  actual two official archives.
- Full RAVDESS audio and any derived media remain outside public Git.
