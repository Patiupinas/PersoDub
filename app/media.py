"""ffmpeg helpers: probe durations, mux, pad/trim to length, cut a clip.

Lowest layer -- imports nothing from app/ except config/logging and the
timeout formula (app/timeouts.py, itself a leaf).
"""
import os
import re
import subprocess
from typing import Callable, Optional

from app.timeouts import scaled_timeout


def stream_duration(path: str, stream: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "stream=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    # ffmpeg 7.x appends a trailing comma to csv output -> strip it and convert to number
    return float(out.stdout.strip().splitlines()[0].rstrip(","))


def video_duration(path: str) -> float:
    return stream_duration(path, "v:0")


def probe_size(path: str, timeout: Optional[float] = None, check: bool = True):
    """The video's pixel width and height as ffprobe reads them -- the one
    probe under every size the app asks for. Raises CalledProcessError when
    ffprobe fails (unless check=False, which reads whatever it printed) and
    ValueError when it gives no size; a missing ffprobe (OSError) or a
    timeout raise as they come. What a failure means is each caller's own:
    video_size below says (0, 0), app/ratio.py refuses, and
    app/api/results.py draws on a 1080p canvas.
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        check=check,
    )
    w, h = (int(x) for x in out.stdout.strip().split(",")[:2])
    return w, h


def video_size(path: str):
    """The video's pixel width and height, or (0, 0) when ffprobe will not say.

    For work described in the frame's own coordinates -- the band the subtitle
    eraser is pointed at, which app/mcp_server.py works out from words like
    "bottom". Zeros rather than a guessed size: a band measured against the
    wrong frame would clean the wrong part of the picture, so the caller has
    to be told instead.
    """
    try:
        # check=False: a size ffprobe printed is used even if it then exits
        # non-zero, as this function always did.
        return probe_size(path, check=False)
    except ValueError:
        return 0, 0


def x264_args(crf: str, audio: list) -> list:
    """ffmpeg's output options for a video the app writes again: H.264 at
    the veryfast preset and quality `crf`, 4:2:0 colour (what every player
    opens), the sound as `audio` says, and the index at the front of the
    file so it starts playing before it has all arrived."""
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
            "-pix_fmt", "yuv420p", *audio, "-movflags", "+faststart"]


def _failure(what: str, stderr: Optional[str], paths=()) -> str:
    """The sentence for an ffmpeg run that failed: `what`, then only ffmpeg's
    last line, which is the complaint itself. The lines before it name the
    input file, so a tail of the whole thing put the user's folders on
    screen (and into a bug report) for nothing. ffmpeg names files by their
    full path even in that last line, so each one is cut back to its own
    name: the user learns which file upset it without their folders ending
    up on screen. The paths the caller gave ffmpeg (`paths`) are cut first,
    whole: a folder name can hold a space ("Application Support", a project
    named after its video), and no pattern can see where such a path ends.
    Anything else that starts like a full path is cut after that, at either
    separator, since Windows writes a backslash; words such as
    "Input/output" are not paths and keep their letters. ffmpeg's own label
    for the part that spoke ("[out#0/mp4 @ 000001f21babe040]") is an
    address, not words for the user, so it goes."""
    last = ([ln.strip() for ln in (stderr or "").splitlines() if ln.strip()] or [""])[-1]
    last = re.sub(r"^\[[^\]]*@ [^\]]*\]\s*", "", last)
    for p in paths:
        last = last.replace(p, os.path.basename(p))
    last = re.sub(r"(?<![^\s'\"(])(?:[A-Za-z]:)?[\\/]\S*[\\/](\S+)", r"\1", last)
    return (what + ": " + last) if last else what + "."


def mux(video: str, audio: str, out: str, dur: float) -> subprocess.CompletedProcess:
    """Re-mux a video track with an audio track, padding the audio to `dur` seconds.

    The video stream is copied untouched (-c:v copy); only the audio is (re)encoded.
    """
    return subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", video, "-i", audio,
         "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "256k", "-af", "apad", "-t", f"{dur:.3f}", out],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def ensure_video_length(original_video: str, out_path: str, log: Callable[[str], None]) -> None:
    """🔒 Absolute guarantee: if the output video length differs from the original, rebuild using the original video untouched.

    The Qwen dub export can come out shorter than the video (audio ends first). In that
    case, re-mux the original video track + dubbed audio (silence-padded at the end)
    into a finished file where not a single video frame has been touched.
    """
    try:
        d_orig = video_duration(original_video)
        d_out = video_duration(out_path)
    except Exception as e:
        log(f"   Warning: Length check failed ({str(e)[:60]}) — using the export result as is")
        return
    if abs(d_orig - d_out) <= 0.02:
        return
    log(f"   Video length correction: {d_out:.3f}s → {d_orig:.3f}s (lossless rebuild from original video)")
    tmp = out_path + ".fix.mp4"
    r = mux(original_video, out_path, tmp, d_orig)
    if r.returncode == 0 and os.path.exists(tmp):
        os.replace(tmp, out_path)
    else:
        log(f"   Warning: Length correction failed — keeping the export result ({r.stderr[-80:]})")


def cut_video(path: str, start: float, end: float, on_cut=None) -> None:
    """Keep only [start, end] of the video, in place. Re-encodes so the cut is
    exact (a copy-cut lands on the nearest keyframe, seconds away).

    `on_cut` runs the instant the cut file takes the original's place, before
    anything else can happen. That is where a caller records "this video is cut
    now": recording it a statement later leaves a window where a force-quit
    saves a record that still owes a cut over a video that has already had one,
    and the next run would take the same seconds out twice.
    """
    tmp = path + ".cut.mp4"
    try:
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                            "-i", path, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", tmp],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(_failure("Could not trim the video", r.stderr, (path, tmp)))
        os.replace(tmp, path)
        if on_cut is not None:
            on_cut()
    finally:
        # A cut that died with the output already open (out of disk, a killed
        # encoder) would otherwise leave a half-written .cut.mp4 beside a good
        # input.mp4, in a folder the pipeline later walks.
        if os.path.exists(tmp):
            os.remove(tmp)


def has_audio(path: str) -> bool:
    """Whether the file has a sound track at all."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return bool(out.stdout.strip())


def cut_ranges_command(src: str, out: str, ranges, audio: bool = True, vf: Optional[str] = None) -> list:
    """ffmpeg argv that keeps only `ranges` ([[start, end], ...] in seconds,
    sorted) of src and joins them into one new file.

    Every part is cut with trim/atrim, which is frame- and sample-exact, then
    the parts are joined by the concat filter and encoded once. The picture
    keeps its size and frame rate, the sound its speed: nothing is stretched.
    `vf` is a picture filter run on the joined video in that same encode (the
    black canvas of a picked ratio, app/ratio.py).
    """
    parts, joins = [], ""
    for i, (a, b) in enumerate(ranges):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        joins += f"[v{i}]"
        if audio:
            parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
            joins += f"[a{i}]"
    n = len(ranges)
    joined = "[vj]" if vf else "[v]"
    graph = ";".join(parts) + f";{joins}concat=n={n}:v=1:a={1 if audio else 0}{joined}" + ("[a]" if audio else "")
    if vf:
        graph += f";[vj]{vf}[v]"
    argv = ["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", graph, "-map", "[v]"]
    if audio:
        argv += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    return argv + x264_args("18", []) + [out]


# What "Audio only" can be saved as, and how ffmpeg is asked for each.
AUDIO_CODECS = {"mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], "wav": ["-c:a", "pcm_s16le"]}


def audio_command(src: str, out: str, fmt: str, ranges=None) -> list:
    """ffmpeg argv that writes the sound of src as a new mp3 or wav: all of
    it, or only `ranges` ([[start, end], ...] in seconds) joined the way
    cut_ranges_command joins them."""
    argv = ["ffmpeg", "-y", "-v", "error", "-i", src]
    if ranges:
        parts = [f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]"
                 for i, (a, b) in enumerate(ranges)]
        joins = "".join(f"[a{i}]" for i in range(len(ranges)))
        argv += ["-filter_complex", ";".join(parts) + f";{joins}concat=n={len(ranges)}:v=0:a=1[a]",
                 "-map", "[a]"]
    else:
        argv += ["-vn"]
    return argv + AUDIO_CODECS[fmt] + [out]


def run_new_file(argv: list, seconds: float, what: str) -> None:
    """Run an ffmpeg argv whose last word is a NEW file. A failure raises
    RuntimeError("<what>: <ffmpeg's last line>") with the folders cut off (see
    _failure), and leaves no half-written file behind."""
    out = argv[-1]
    try:
        try:
            r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=scaled_timeout(seconds, 300))
        except subprocess.TimeoutExpired:
            raise RuntimeError(what + ": it took too long.")
        if r.returncode != 0:
            raise RuntimeError(_failure(what, r.stderr, argv))
    except RuntimeError:
        if os.path.exists(out):
            os.remove(out)
        raise


def cut_ranges(path: str, ranges, on_cut=None) -> None:
    """Keep only `ranges` of the video and join them, in place.

    The same promise as cut_video: the joined file takes the original's place
    in one rename, and `on_cut` runs the instant it has, so a caller can
    record "this video is cut now" before anything else can happen.
    """
    tmp = path + ".cut.mp4"
    total = sum(b - a for a, b in ranges)
    try:
        run_new_file(cut_ranges_command(path, tmp, ranges, has_audio(path)), total,
                     "Could not join the kept parts")
        os.replace(tmp, path)
        if on_cut is not None:
            on_cut()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
