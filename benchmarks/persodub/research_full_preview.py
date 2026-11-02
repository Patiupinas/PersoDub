"""Source-exact full-length research preview using frozen, unapproved RU WAVs.

This is deliberately not the A4 release exporter. Its output is an unapproved
listening candidate, with no inferred TRANSLATE/PRESERVE decisions or changes
to the original job. Reuse the product's mux to retain original AAC and video.
"""
import argparse
import hashlib
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

from app import media
from app.vocal_overdub_export import _verify_export_tracks

SR = 48000
CHANNELS = 2
FADE_S = 0.18
SOURCE_SHA = "27066bafbd8769bba2530d82ca3c2cb2fddc6588224cae876ebf30e14e8ec322"
SOURCE_PCM_SHA = "94eeea9d834d91d7bfb2c89551b7b053cbee22399e0ec7564853a7b0090e8cf4"
ORIGINAL_GAIN = 10 ** (-16 / 20)
RU_GAIN = 10 ** (-2 / 20)


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for piece in iter(lambda: source.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def read_source_pcm(path):
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (SR, CHANNELS, 2):
            raise ValueError("Original source must be 48kHz stereo PCM16")
        raw = source.readframes(source.getnframes())
    return np.frombuffer(raw, dtype="<i2").reshape(-1, CHANNELS).copy()


def read_voice_pcm(path):
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise ValueError("Voice must be mono PCM16")
        if source.getframerate() == SR:
            return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").copy()
        if source.getframerate() != 24000:
            raise ValueError("Voice sample rate must be 24000 or 48000")
    # The project already requires FFmpeg. Decode the same model WAV at 48k.
    run = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ar", str(SR),
         "-ac", "1", "-f", "s16le", "pipe:1"],
        capture_output=True, check=True, timeout=120,
    )
    return np.frombuffer(run.stdout, dtype="<i2").copy()


def splice_unapproved_pcm(source_pcm, manifest, voice_root, offset_s=145.0,
                          overrides=None):
    """Return one exploratory mix plus an exact protected-frame mask.

    No action or review authority is derived from the source metadata.
    """
    cases = manifest["cases"]
    if not cases or manifest.get("reviewed_a4") is not False:
        raise ValueError("Expected a frozen, explicitly unreviewed research manifest")
    mixed = source_pcm.copy()
    active = np.zeros(len(mixed), dtype=bool)
    receipts = []
    for case in cases:
        name = (overrides or {}).get(case["id"], case["output_file"])
        path = Path(name)
        if not path.is_absolute():
            path = Path(voice_root) / path
        speech = read_voice_pcm(path)
        if not len(speech):
            raise ValueError("Empty synthesized voice clip")
        source_offset = case.get("offset_s", offset_s)
        onset = source_offset + case["start"]
        # The legacy research script placed one actual 169.36s speech cue
        # at 168.36s. Do not preserve this premature TTS onset in new mixes.
        if case.get("source_start") is not None:
            onset = max(onset, case["source_start"])
        start = round(onset * SR)
        end = start + len(speech)
        slot_end = source_offset + case["slot_end"]
        if case.get("source_end") is not None:
            slot_end = min(slot_end, case["source_end"])
        limit = round(slot_end * SR)
        if start < 0 or end > limit or end > len(source_pcm) or active[start:end].any():
            raise ValueError("Voice exceeds source slot, video end or adjacent speech")
        active[start:end] = True
        gain = np.ones(len(speech), dtype=np.float64)
        fade = min(round(FADE_S * SR), len(speech) // 4)
        if fade:
            ramp = (1 - np.cos(np.linspace(0, np.pi, fade))) / 2
            gain[:fade] = ramp
            gain[-fade:] = ramp[::-1]
        orig_factor = 1.0 + (ORIGINAL_GAIN - 1.0) * gain
        voice_factor = RU_GAIN * gain
        base = source_pcm[start:end].astype(np.float64)
        voice = speech.astype(np.float64)[:, None]
        result = base * orig_factor[:, None] + voice * voice_factor[:, None]
        if np.max(np.abs(result)) > 32767.5:
            raise ValueError("Experimental mix would exceed PCM16 peak")
        mixed[start:end] = np.rint(result).astype("<i2")
        receipts.append({
            "id": case["id"], "start_frame": start, "end_frame": end,
            "slot_end_frame": limit, "voice_wav_sha256": file_sha(path),
            "voice_duration_seconds": round(len(speech) / SR, 5),
            "source_authority": "UNREVIEWED_MODEL_AUTHORED_DRAFT",
        })
    if not np.array_equal(mixed[~active], source_pcm[~active]):
        raise AssertionError("Original source changed outside experimental voice samples")
    return mixed, active, receipts


def write_pcm(path, pcm):
    path = Path(path)
    if path.exists():
        raise FileExistsError(str(path))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(SR)
        output.writeframes(pcm.astype("<i2", copy=False).tobytes())


def build(args):
    for dest in (args.output_wav, args.output_mp4, args.receipt):
        if Path(dest).exists():
            raise FileExistsError(str(dest))
    actual_source = file_sha(args.video)
    if actual_source != SOURCE_SHA:
        raise ValueError("Original video SHA differs from frozen research lesson")
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    extra_source = None
    omitted = []
    if args.additional_manifest is not None:
        extra = json.loads(Path(args.additional_manifest).read_text(encoding="utf-8"))
        if (extra.get("status") != "OBSERVED_UNREVIEWED_TTS_RESEARCH"
                or extra.get("source_video_sha256") != SOURCE_SHA):
            raise ValueError("Additional research translations have incorrect provenance")
        extra_source = extra.get("source_srt_sha256")
        if args.source_srt is None or file_sha(args.source_srt) != extra_source:
            raise ValueError("Additional Russian text must match the exact bounded-source SRT")
        for row in extra["files"]:
            if row.get("human_a4_approved") is not False:
                raise ValueError("Additional research voice claims unknown A4 authority")
            if row.get("status") != "FITS_SOURCE_SLOT_UNREVIEWED":
                omitted.append({"id": row["id"], "reason": row.get("status")})
                continue
            manifest["cases"].append({
                "id": row["id"], "start": row["start"],
                "slot_end": row["slot_end"],
                "output_file": str(Path(args.additional_manifest).parent /
                                   "new-ru-wavs" / row["wave_file"]),
                "offset_s": 0.0,
            })
    source_wav_sha = file_sha(args.source_wav)
    if source_wav_sha != SOURCE_PCM_SHA:
        raise ValueError("Source PCM is not the frozen full-video 48kHz decode")
    source_pcm = read_source_pcm(args.source_wav)
    overrides = {}
    if args.variant == "clean-icl":
        for stem in ("b", "c", "d"):
            overrides[stem] = str(Path(args.icl_root) / f"qwen-{stem}-clean_icl.wav")
    mixed, active, receipts = splice_unapproved_pcm(source_pcm, manifest, args.voice_root,
                                                     overrides=overrides)
    write_pcm(args.output_wav, mixed)
    run = media.mux_overdub(str(args.video), str(args.output_wav),
                            str(args.output_mp4), media.video_duration(str(args.video)))
    if run.returncode:
        raise RuntimeError(run.stderr.strip().splitlines()[-1])
    _verify_export_tracks(args.output_mp4)
    report = {
        "status": "OBSERVED_RESEARCH_PREVIEW_NOT_A4_APPROVED",
        "video_sha256": actual_source, "source_pcm_sha256": source_wav_sha,
        "source_pcm_frames": len(source_pcm), "sample_rate": SR,
        "video_duration_seconds": media.stream_duration(str(args.video), "a:0"),
        "preview_variant": args.variant, "experimental_voice_cases": receipts,
        "additional_repaired_source_srt_sha256": extra_source,
        "omitted_overlong_cases": omitted,
        "active_voice_frames": int(active.sum()),
        "protected_source_frames_exact": int((~active).sum()),
        "human_a4_approved": False, "native_russian_quality_verified": False,
        "original_video_and_aac_copied_by_mux": True,
        "original_packet_identity_rechecked": False,
        "output_wav_sha256": file_sha(args.output_wav),
        "output_mp4_sha256": file_sha(args.output_mp4),
    }
    Path(args.receipt).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "preview_variant": args.variant,
        "total_frames": len(source_pcm), "active_frames": int(active.sum()),
        "unmodified_frames": int((~active).sum()), "clips": len(receipts),
        "output_mp4": str(args.output_mp4), "receipt": str(args.receipt),
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--source-wav", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--voice-root", type=Path, required=True)
    parser.add_argument("--icl-root", type=Path)
    parser.add_argument("--additional-manifest", type=Path)
    parser.add_argument("--source-srt", type=Path)
    parser.add_argument("--variant", choices=("timbre", "clean-icl"), default="timbre")
    parser.add_argument("--output-wav", type=Path, required=True)
    parser.add_argument("--output-mp4", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.variant == "clean-icl" and args.icl_root is None:
        parser.error("--icl-root required for clean-icl variant")
    build(args)


if __name__ == "__main__":
    main()
