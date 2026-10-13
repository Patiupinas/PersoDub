# -*- coding: utf-8 -*-
"""Turn a finished Perso dub into a locally editable job.

Perso serves everything the app's own edit/remake machinery reads: the script
(original + translated + timings + speakers), one audio file per sentence, and
the background bed. This module downloads them ONCE and writes exactly the
files a locally-dubbed job leaves behind -- after that, editing a line,
remaking its voice and rebuilding the video all run through the code paths
that already exist, with no Perso re-billing.

Verified live 2026-08-31 (project 409873): script via /script, per-sentence
audio via each sentence's audioUrl, background via download?target=backgroundAudio.
"""
import contextlib
import json
import os
import shutil
import subprocess

from app.text.srt import build_srt, parse_srt


def _ffmpeg_to_wav(src: str, dest: str) -> None:
    """Any downloaded audio -> PCM wav the assembler can read (48 kHz)."""
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ar", "48000", dest],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("could not convert %s: %s" % (os.path.basename(src),
                                                         (r.stderr or "").strip()[-120:]))


def _cue_count(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return len(parse_srt(f.read()))
    except OSError:
        return -1


def fetch_line(pc, audio_url: str, work_dir: str, n: int, to_wav=None) -> str:
    """Bring line n's voice (0-based, as the files are numbered) home from
    Perso. The old wav stays whole until the new one is: a download or a
    conversion that fails halfway leaves the line sounding as it did."""
    to_wav = to_wav or _ffmpeg_to_wav
    src = os.path.join(work_dir, "perso_line_%d.src" % n)
    new = os.path.join(work_dir, "perso_line_%d.new.wav" % n)
    wav = os.path.join(work_dir, "qwen_line_%d.wav" % n)
    try:
        pc.download_media(audio_url, src)
        to_wav(src, new)
        os.replace(new, wav)
    finally:
        for leftover in (src, new):
            with contextlib.suppress(OSError):
                os.remove(leftover)
    return wav


def materialize(pc, project_seq: int, work_dir: str, language: str,
                to_wav=None, log=None, refresh: bool = False, space_seq=None) -> dict:
    """Download a Perso dub's parts and write the local job files.

    Idempotent: audio already on disk is not fetched again, and the script
    files are simply rewritten with the same content. Never touches
    edited.srt -- a user's edits survive a re-run.

    refresh=True is for a project Perso has worked on again (a proofread):
    every line's voice is fetched afresh, over the one on disk. The background
    bed is the source video's and does not change, so it is kept.
    """
    to_wav = to_wav or _ffmpeg_to_wav
    log = log or (lambda m: None)
    os.makedirs(work_dir, exist_ok=True)

    log("Reading the script from Perso…")
    sents = pc.get_project_script(project_seq, space_seq).get("sentences") or []

    cues_t, cues_o, spans, lines = [], [], [], []
    for n, s in enumerate(sents):
        start = (s.get("offsetMs") or 0) / 1000.0
        end = start + (s.get("durationMs") or 0) / 1000.0
        idx = s.get("speakerOrderIndex")
        spk = "S%s" % (idx if idx is not None else 0)
        cues_t.append({"start": start, "end": end, "text": s.get("translatedText") or ""})
        cues_o.append({"start": start, "end": end, "text": s.get("originalText") or ""})
        spans.append({"start": start, "end": end, "speaker": spk})
        lines.append({"i": n, "start": start, "gain": None, "speaker": spk})

        wav = os.path.join(work_dir, "qwen_line_%d.wav" % n)
        if refresh or not os.path.exists(wav):
            if s.get("audioUrl"):
                log("Fetching line %d of %d…" % (n + 1, len(sents)))
                fetch_line(pc, s["audioUrl"], work_dir, n, to_wav)
            else:
                # Happens right after a server-side change (e.g. a new
                # speaker): Perso is still regenerating that sentence.
                log("Line %d has no audio on Perso yet (still being made) -- "
                    "run Make it editable again later to fetch it." % (n + 1))

    bg = os.path.join(work_dir, "background.wav")
    if not os.path.exists(bg):
        log("Fetching the background bed…")
        src = os.path.join(work_dir, "perso_background.src")
        pc.download_target(project_seq, "backgroundAudio", src, space_seq)
        to_wav(src, bg)
        with contextlib.suppress(OSError):
            os.remove(src)

    with open(os.path.join(work_dir, "translated.srt"), "w", encoding="utf-8") as f:
        f.write(build_srt(cues_t))
    # A line edited through Perso has the new words as its source there
    # (PersoClient.edit_sentence), and a proofread makes that permanent. The
    # video's own words do not change, so on a refresh the ones here stay.
    source = os.path.join(work_dir, "original.srt")
    if not (refresh and _cue_count(source) == len(cues_o)):
        with open(source, "w", encoding="utf-8") as f:
            f.write(build_srt(cues_o))
    with open(os.path.join(work_dir, "speakers.json"), "w", encoding="utf-8") as f:
        json.dump(spans, f, ensure_ascii=False)
    with open(os.path.join(work_dir, "lines.json"), "w", encoding="utf-8") as f:
        json.dump({"language": language, "lines": lines}, f, ensure_ascii=False)

    # One reference per speaker, for cloning that voice again on a remake:
    # the speaker's LONGEST line whose audio actually landed on disk.
    refs = {}
    best = {}
    for n, s in enumerate(sents):
        idx = s.get("speakerOrderIndex")
        spk = "S%s" % (idx if idx is not None else 0)
        if not os.path.exists(os.path.join(work_dir, "qwen_line_%d.wav" % n)):
            continue
        if spk not in best or (s.get("durationMs") or 0) > (sents[best[spk]].get("durationMs") or 0):
            best[spk] = n
    for spk, n in best.items():
        ref = os.path.join(work_dir, "qwen_ref_%s.wav" % spk)
        if not os.path.exists(ref):
            shutil.copyfile(os.path.join(work_dir, "qwen_line_%d.wav" % n), ref)
        refs[spk] = {"ref_text": sents[n].get("translatedText") or ""}
    with open(os.path.join(work_dir, "speaker_refs.json"), "w", encoding="utf-8") as f:
        json.dump(refs, f, ensure_ascii=False)

    missing = sum(1 for n in range(len(sents))
                  if not os.path.exists(os.path.join(work_dir, "qwen_line_%d.wav" % n)))
    if missing:
        log("%d line(s) are still being made on Perso -- refetch later." % missing)
    log("This dubbing is editable now.")
    return {"lines": len(lines), "speakers": len(best), "missing_audio": missing}
