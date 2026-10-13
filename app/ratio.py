"""The picture inside a canvas of another shape: 9:16, 16:9, 1:1 or 4:5.

The player's Ratio button shows a video centred in a canvas of the picked
shape with black filling the rest, and every file the app saves for the user
can be written the same way. This file is the arithmetic, the one ffmpeg
filter that does it, and the small record of which shape a job was last
shown in (view.json in the job's own folder, beside subtitle_style.json).

The picture is never scaled. The canvas is the smallest one of the wanted
shape that holds the picture at its own size, so one side of the canvas is the
picture's own and the other grows; both are rounded up to even numbers because
the encoder's 4:2:0 colour needs them.
"""
import json
import os
import subprocess
from typing import Optional

from app import media
from app.i18n import t

RATIOS = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5)}
ORIGINAL = "original"


# Plain errors, not HTTP ones: this is not an API module. The routes answer
# them in their own words (app/api/_shared.py ratio_errors_as_http).
class UnknownRatioError(ValueError):
    """A shape the Ratio menu does not offer (the routes' 422)."""


class CanvasError(RuntimeError):
    """The video could not be measured, or ffmpeg could not put it in its
    canvas (the routes' 503)."""


def wanted(ratio: Optional[str]) -> Optional[str]:
    """The shape asked for, or None for "leave the video as it is".

    Nothing, "" and "original" all mean the same: no canvas. Anything else
    must be one of the four the menu offers."""
    if ratio is None or ratio == "" or ratio == ORIGINAL:
        return None
    if ratio not in RATIOS:
        raise UnknownRatioError(t("ratio must be original, 9:16, 16:9, 1:1 or 4:5"))
    return ratio


def _even_up(n: int) -> int:
    return n + (n % 2)


def canvas_size(width: int, height: int, ratio: Optional[str]):
    """(W, H) of the canvas for a width x height picture, or None when the
    picture needs no canvas: no shape asked for, or it has that shape already.
    """
    ratio = wanted(ratio)
    if ratio is None:
        return None
    rw, rh = RATIOS[ratio]
    if width * rh >= height * rw:
        # The picture is the wider of the two: its width is the canvas's.
        w, h = width, -(-width * rh // rw)
    else:
        w, h = -(-height * rw // rh), height
    w, h = _even_up(w), _even_up(h)
    # A shape the picture already has, give or take the rounding: 854x480 is
    # 16:9 to everyone, and two lines of black under it would be a mistake.
    if w - width <= 2 and h - height <= 2:
        return None
    return w, h


def pad_filter(width: int, height: int, ratio: Optional[str]) -> Optional[str]:
    """The ffmpeg filter that puts the picture in the middle of its canvas,
    black around it, or None when there is nothing to add."""
    size = canvas_size(width, height, ratio)
    if size is None:
        return None
    return "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black" % size


def video_size(path: str):
    """The picture's width and height as ffprobe reads them."""
    try:
        return media.probe_size(path, timeout=30)
    except Exception:
        raise CanvasError(t("Could not read this video's size."))


def pad_filter_for(path: str, ratio: Optional[str]) -> Optional[str]:
    """pad_filter for a file on disk. The file is only probed when a shape was
    asked for, so a caller that passes no ratio runs exactly as it did."""
    if wanted(ratio) is None:
        return None
    return pad_filter(*video_size(path), ratio)


def pad_command(src: str, out: str, vf: str) -> list:
    """ffmpeg argv that writes src into out through the filter. The picture is
    encoded again (padding changes every frame); the sound is copied."""
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", src, "-vf", vf,
            *media.x264_args("18", ["-c:a", "copy"]), out]


def pad_to(src: str, out: str, ratio: Optional[str]) -> bool:
    """Write src into out inside the canvas. False, and nothing written, when
    the video needs no canvas."""
    vf = pad_filter_for(src, ratio)
    if vf is None:
        return False
    run = subprocess.run(pad_command(src, out, vf), capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if run.returncode != 0:
        if os.path.exists(out):
            os.remove(out)
        # "the 9:16 shape", not "9:16": ffmpeg's reason follows a colon, and
        # "to 9:16: Invalid data" runs the shape and the reason together.
        raise CanvasError(media._failure(t("ffmpeg could not fit this video to the {ratio} shape", ratio=ratio),
                                         run.stderr, (src, out)))
    return True


def pad_file(path: str, ratio: Optional[str]) -> None:
    """Put a file that was just saved inside the canvas, in place. The one line
    a save route adds: with no ratio it returns before touching anything."""
    tmp = path + ".ratio.mp4"
    try:
        if pad_to(path, tmp, ratio):
            os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def padded_copy(src: str, work: str, ratio: Optional[str]) -> str:
    """The path to serve for src in this shape: src itself when it needs no
    canvas, else a copy kept in the job's folder and made again only when src
    is newer than it."""
    vf = pad_filter_for(src, ratio)
    if vf is None:
        return src
    built = os.path.join(work, "ratio-%s.mp4" % ratio.replace(":", "x"))
    if not os.path.exists(built) or os.path.getmtime(src) > os.path.getmtime(built):
        pad_to(src, built, ratio)
    return built


# ---- Which shape a job was last shown in ----------------------------------

def load_view(work: str) -> dict:
    try:
        with open(os.path.join(work, "view.json"), encoding="utf-8") as f:
            ratio = json.load(f).get("ratio")
    except (OSError, ValueError, AttributeError):
        ratio = None
    return {"ratio": ratio if ratio in RATIOS else ORIGINAL}


def save_view(work: str, body: dict) -> dict:
    view = {"ratio": wanted((body or {}).get("ratio")) or ORIGINAL}
    with open(os.path.join(work, "view.json"), "w", encoding="utf-8") as f:
        json.dump(view, f)
    return view
