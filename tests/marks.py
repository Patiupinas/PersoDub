"""Shared test marks. CI runs the suite without ffmpeg (see .github/workflows),
so every test that really runs ffmpeg/ffprobe carries @needs_ffmpeg."""
import shutil

import pytest

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg is not installed")
