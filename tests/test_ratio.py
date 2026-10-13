"""The Ratio button's other half: every video the app saves can be written
inside a canvas of the picked shape, black around the picture, and a job
remembers which shape it was left on. The picture itself is never scaled.

ffmpeg is a recorder in most of these, as in test_export_subtitled.py; the
last test runs the real one on a generated clip when it is installed.
"""
import os
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import engines_status, ratio, state
from app.api import _launch as launch_api
from app.api import downloads as dl
from app.api import dub as dub_api
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


# ---- The arithmetic -------------------------------------------------------

def test_a_landscape_picture_in_9_16_keeps_its_width_and_grows_tall():
    # 1920 * 16 / 9 = 3413.3: up to the next whole line, then to an even one.
    assert ratio.canvas_size(1920, 1080, "9:16") == (1920, 3414)
    assert ratio.canvas_size(1280, 720, "9:16") == (1280, 2276)


def test_a_portrait_picture_in_16_9_keeps_its_height_and_grows_wide():
    assert ratio.canvas_size(1080, 1920, "16:9") == (3414, 1920)


def test_a_square_canvas_is_the_pictures_longer_side():
    assert ratio.canvas_size(1920, 1080, "1:1") == (1920, 1920)
    assert ratio.canvas_size(1080, 1920, "1:1") == (1920, 1920)


def test_4_5_is_taller_than_a_landscape_picture_and_wider_than_a_portrait_one():
    assert ratio.canvas_size(1920, 1080, "4:5") == (1920, 2400)
    # 1920 * 4 / 5 = 1536, wider than the 1080 picture.
    assert ratio.canvas_size(1080, 1920, "4:5") == (1536, 1920)


def test_original_and_nothing_mean_no_canvas():
    for r in (None, "", "original"):
        assert ratio.canvas_size(1920, 1080, r) is None
        assert ratio.pad_filter(1920, 1080, r) is None


def test_a_picture_that_already_has_the_shape_is_left_alone():
    assert ratio.canvas_size(1920, 1080, "16:9") is None
    assert ratio.canvas_size(1080, 1920, "9:16") is None
    assert ratio.canvas_size(1080, 1080, "1:1") is None
    # 854x480 is "16:9" to everyone but the arithmetic (it is 1 pixel short).
    assert ratio.canvas_size(854, 480, "16:9") is None


@pytest.mark.parametrize("w,h", [(1920, 1080), (1080, 1920), (853, 481), (640, 360), (1, 1)])
@pytest.mark.parametrize("r", list(ratio.RATIOS))
def test_the_canvas_is_even_holds_the_picture_and_never_scales_it(w, h, r):
    size = ratio.canvas_size(w, h, r)
    if size is None:
        return
    cw, ch = size
    assert cw % 2 == 0 and ch % 2 == 0
    assert cw >= w and ch >= h
    # One side is the picture's own (give or take the round up to even).
    assert cw - w <= 1 or ch - h <= 1
    rw, rh = ratio.RATIOS[r]
    assert abs(cw / ch - rw / rh) < 2 / min(cw, ch) + 1e-9


def test_an_unknown_shape_is_refused():
    # A plain error here; the routes answer it as 422 (test_the_dub_refuses_a_shape_it_does_not_know).
    with pytest.raises(ratio.UnknownRatioError) as e:
        ratio.canvas_size(1920, 1080, "21:9")
    assert str(e.value) == "ratio must be original, 9:16, 16:9, 1:1 or 4:5"


# ---- The ffmpeg arguments -------------------------------------------------

def test_the_filter_centres_the_picture_on_black():
    assert ratio.pad_filter(1920, 1080, "9:16") == "pad=1920:3414:(ow-iw)/2:(oh-ih)/2:black"
    assert ratio.pad_filter(1080, 1920, "1:1") == "pad=1920:1920:(ow-iw)/2:(oh-ih)/2:black"


def test_the_command_encodes_the_picture_again_and_copies_the_sound():
    cmd = ratio.pad_command("in.mp4", "out.mp4", "pad=2:2")
    assert cmd[0] == "ffmpeg" and cmd[-1] == "out.mp4"
    assert cmd[cmd.index("-i") + 1] == "in.mp4"
    assert cmd[cmd.index("-vf") + 1] == "pad=2:2"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    # No scale anywhere: the picture keeps its own pixels.
    assert not any("scale" in str(a) for a in cmd)


class _Ran:
    def __init__(self):
        self.calls = []
        self.returncode = 0
        self.stderr = ""

    def __call__(self, cmd, **_kw):
        # check_output runs through subprocess.run too: no ffprobe here, so the
        # subtitle route falls back to its 1080p canvas as in its own tests.
        if cmd[0] == "ffprobe":
            raise OSError("no ffprobe in tests")
        self.calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"PADDED")
        return self


def _vf(cmd):
    return cmd[cmd.index("-vf") + 1]


@pytest.fixture
def ran(monkeypatch):
    r = _Ran()
    monkeypatch.setattr(subprocess, "run", r)
    monkeypatch.setattr(ratio, "video_size", lambda path: (1920, 1080))
    return r


def _own_folder(tmp_path):
    """A folder with nothing else in it (conftest keeps a workspace in tmp_path)."""
    d = tmp_path / "saved"
    d.mkdir()
    return d


def test_pad_file_without_a_ratio_touches_nothing(ran, tmp_path):
    f = _own_folder(tmp_path) / "v.mp4"
    f.write_bytes(b"AS IT WAS")
    for r in (None, "", "original", "16:9"):   # 16:9 is the picture's own shape
        ratio.pad_file(str(f), r)
    assert ran.calls == []
    assert f.read_bytes() == b"AS IT WAS"
    assert os.listdir(f.parent) == ["v.mp4"]


def test_pad_file_replaces_the_file_with_the_padded_one(ran, tmp_path):
    f = _own_folder(tmp_path) / "v.mp4"
    f.write_bytes(b"AS IT WAS")
    ratio.pad_file(str(f), "9:16")
    assert len(ran.calls) == 1
    assert _vf(ran.calls[0]) == "pad=1920:3414:(ow-iw)/2:(oh-ih)/2:black"
    assert f.read_bytes() == b"PADDED"
    assert os.listdir(f.parent) == ["v.mp4"]   # no temporary file left behind


def test_a_failed_pad_leaves_the_saved_file_as_it_was(ran, tmp_path):
    ran.returncode = 1
    ran.stderr = "boom"
    f = _own_folder(tmp_path) / "v.mp4"
    f.write_bytes(b"AS IT WAS")
    with pytest.raises(ratio.CanvasError) as e:
        ratio.pad_file(str(f), "1:1")
    assert str(e.value) == "ffmpeg could not fit this video to the 1:1 shape: boom"
    assert f.read_bytes() == b"AS IT WAS"
    assert os.listdir(f.parent) == ["v.mp4"]


# ---- The routes -----------------------------------------------------------

@pytest.fixture(autouse=True)
def _all_engines_available(monkeypatch):
    monkeypatch.setattr(engines_status, "gemma_available", lambda: True)
    monkeypatch.setattr(engines_status, "hunyuan_available", lambda: True)
    monkeypatch.setattr(engines_status, "qwen_available", lambda: True)
    monkeypatch.setattr(engines_status, "gemma_status", lambda: "available")
    monkeypatch.setattr(engines_status, "hunyuan_status", lambda: "available")
    monkeypatch.setattr(engines_status, "qwen_status", lambda: "available")
    monkeypatch.setattr(engines_status, "gemini_available", lambda: True)
    monkeypatch.setattr(engines_status, "perso_available", lambda: True)
    monkeypatch.setattr(launch_api, "missing_models", lambda *a, **kw: [])


def _done_job(monkeypatch):
    def fake_run_dub(**kw):
        work = os.path.dirname(kw["out_path"])
        with open(kw["out_path"], "wb") as f:
            f.write(b"FAKEDUB")
        with open(os.path.join(work, "translated.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
        return {"job_id": "x", "out_path": kw["out_path"], "num_segments": 1}

    monkeypatch.setattr(dub_api, "run_dub", fake_run_dub)
    jid = client.post("/api/dub/start", data={"language_code": "ko"},
                      files={"video": ("v.mp4", b"FAKEMP4", "video/mp4")}).json()["job_id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        job = client.get(f"/api/dub/jobs/{jid}").json()
        if job["status"] == "done":
            return jid, os.path.dirname(job["result"]["out_path"])
        time.sleep(0.02)
    raise AssertionError("job never finished")


def test_the_dub_downloads_as_it_is_without_a_ratio(monkeypatch, ran):
    jid, _work = _done_job(monkeypatch)
    for url in (f"/api/dub/result/{jid}", f"/api/dub/result/{jid}?ratio=original"):
        r = client.get(url)
        assert r.status_code == 200 and r.content == b"FAKEDUB"
    assert ran.calls == []


def test_the_dub_downloads_padded_and_the_padded_copy_is_kept(monkeypatch, ran):
    jid, work = _done_job(monkeypatch)
    r = client.get(f"/api/dub/result/{jid}?ratio=9:16")
    assert r.status_code == 200 and r.content == b"PADDED"
    assert 'filename="dub_ko.mp4"' in r.headers["content-disposition"]
    assert ran.calls[0][-1] == os.path.join(work, "ratio-9x16.mp4")
    assert _vf(ran.calls[0]) == "pad=1920:3414:(ow-iw)/2:(oh-ih)/2:black"
    # Asked again, the copy is served; a remade dub makes it again.
    client.get(f"/api/dub/result/{jid}?ratio=9:16")
    assert len(ran.calls) == 1
    later = time.time() + 5
    os.utime(os.path.join(work, "dubbed.mp4") if os.path.exists(os.path.join(work, "dubbed.mp4"))
             else client.get(f"/api/dub/jobs/{jid}").json()["result"]["out_path"], (later, later))
    client.get(f"/api/dub/result/{jid}?ratio=9:16")
    assert len(ran.calls) == 2


def test_the_dub_refuses_a_shape_it_does_not_know(monkeypatch, ran):
    jid, _work = _done_job(monkeypatch)
    assert client.get(f"/api/dub/result/{jid}?ratio=2:1").status_code == 422


_REAL_VIDEO_SIZE = ratio.video_size


def test_the_routes_answer_a_refused_or_failed_canvas_in_its_own_words(monkeypatch, ran, tmp_path):
    def answer(r):
        return r.status_code, r.json()
    did = _held(monkeypatch, tmp_path)
    jid, _work = _done_job(monkeypatch)
    unknown = (422, {"detail": "ratio must be original, 9:16, 16:9, 1:1 or 4:5"})
    assert answer(client.get(f"/api/dub/result/{jid}?ratio=2:1")) == unknown
    assert answer(client.get(f"/api/dub/result/{jid}/subtitled?preset=clean&ratio=2:1")) == unknown
    assert answer(client.put(f"/api/dub/jobs/{jid}/view", json={"ratio": "2:1"})) == unknown
    assert answer(client.post(f"/api/downloads/{did}/save",
                              json={"dir": str(tmp_path / "out"), "ratio": "2:1"})) == unknown
    ran.returncode, ran.stderr = 1, "boom"
    assert answer(client.get(f"/api/dub/result/{jid}?ratio=9:16")) == (
        503, {"detail": "ffmpeg could not fit this video to the 9:16 shape: boom"})
    assert answer(client.post(f"/api/downloads/{did}/save",
                              json={"dir": str(tmp_path / "out"), "ratio": "9:16"})) == (
        503, {"detail": "ffmpeg could not fit this video to the 9:16 shape: boom"})
    # No ffprobe here (the recorder refuses it), so the size cannot be read.
    monkeypatch.setattr(ratio, "video_size", _REAL_VIDEO_SIZE)
    unreadable = (503, {"detail": "Could not read this video's size."})
    assert answer(client.get(f"/api/dub/result/{jid}?ratio=1:1")) == unreadable
    assert answer(client.get(f"/api/dub/result/{jid}/subtitled?preset=clean&ratio=1:1")) == unreadable
    assert answer(client.post(f"/api/downloads/{did}/save",
                              json={"dir": str(tmp_path / "out"), "ratio": "1:1"})) == unreadable


def test_the_subtitled_video_is_padded_after_the_subtitles_are_drawn(monkeypatch, ran):
    jid, work = _done_job(monkeypatch)
    assert client.get(f"/api/dub/result/{jid}/subtitled?preset=clean&ratio=1:1").status_code == 200
    vf = _vf(ran.calls[0])
    assert vf.startswith("ass=filename=")
    assert vf.endswith(",pad=1920:1920:(ow-iw)/2:(oh-ih)/2:black")
    assert ran.calls[0][-1] == os.path.join(work, "subtitled-clean-r1x1.mp4")
    # Without a ratio it is the file and the filter it always was.
    assert client.get(f"/api/dub/result/{jid}/subtitled?preset=clean").status_code == 200
    assert "pad=" not in _vf(ran.calls[1])
    assert ran.calls[1][-1] == os.path.join(work, "subtitled-clean.mp4")


def test_a_job_remembers_the_ratio_it_was_left_on(monkeypatch):
    jid, work = _done_job(monkeypatch)
    assert client.get(f"/api/dub/jobs/{jid}/view").json() == {"ratio": "original"}
    r = client.put(f"/api/dub/jobs/{jid}/view", json={"ratio": "4:5"})
    assert r.status_code == 200 and r.json() == {"ratio": "4:5"}
    assert os.path.exists(os.path.join(work, "view.json"))
    assert client.get(f"/api/dub/jobs/{jid}/view").json() == {"ratio": "4:5"}
    assert client.put(f"/api/dub/jobs/{jid}/view", json={"ratio": "3:2"}).status_code == 422
    assert client.get(f"/api/dub/jobs/{jid}/view").json() == {"ratio": "4:5"}
    assert client.put(f"/api/dub/jobs/{jid}/view", json={"ratio": "original"}).json() == {"ratio": "original"}
    assert client.get("/api/dub/jobs/nope/view").status_code == 404


def _held(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setattr(dl, "probe_source", lambda url: {"title": "clip", "duration_sec": 46})

    def fake_fetch(url, dest, log=None, cancel_check=None):
        with open(dest, "wb") as f:
            f.write(b"video bytes")
    monkeypatch.setattr(dl, "fetch_source", fake_fetch)
    did = client.post("/api/downloads", json={"url": "https://youtu.be/x"}).json()["id"]
    for _ in range(200):
        if client.get(f"/api/downloads/{did}").json()["status"] == "ready":
            return did
        time.sleep(0.01)
    raise AssertionError("download never became ready")


def test_a_draft_saves_as_it_is_without_a_ratio_and_padded_with_one(monkeypatch, ran, tmp_path):
    did = _held(monkeypatch, tmp_path)
    plain = client.post(f"/api/downloads/{did}/save", json={"dir": str(tmp_path / "out")})
    assert plain.status_code == 200 and ran.calls == []
    assert open(plain.json()["path"], "rb").read() == b"video bytes"
    padded = client.post(f"/api/downloads/{did}/save",
                         json={"dir": str(tmp_path / "out"), "ratio": "9:16"})
    assert padded.status_code == 200, padded.text
    assert len(ran.calls) == 1 and "pad=1920:3414" in _vf(ran.calls[0])
    assert open(padded.json()["path"], "rb").read() == b"PADDED"
    # Nothing but the two saved videos in the folder.
    assert sorted(os.listdir(os.path.dirname(padded.json()["path"]))) == sorted(
        [os.path.basename(plain.json()["path"]), os.path.basename(padded.json()["path"])])


def test_a_draft_refuses_a_shape_it_does_not_know(monkeypatch, ran, tmp_path):
    did = _held(monkeypatch, tmp_path)
    r = client.post(f"/api/downloads/{did}/save", json={"dir": str(tmp_path), "ratio": "7:3"})
    assert r.status_code == 422


# ---- The real thing -------------------------------------------------------

@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="ffmpeg is not installed")
@pytest.mark.parametrize("size,r,expect", [
    ("320x180", "9:16", (320, 570)),
    ("180x320", "16:9", (570, 320)),
    ("320x180", "1:1", (320, 320)),
    ("320x180", "4:5", (320, 400)),
])
def test_ffmpeg_writes_the_canvas_with_the_picture_unscaled_in_the_middle(tmp_path, size, r, expect):
    src = str(tmp_path / "src.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=white:s=%s:d=0.4:r=10" % size, "-pix_fmt", "yuv420p", src], check=True)
    ratio.pad_file(src, r)
    assert ratio.video_size(src) == expect
    # One frame as grey bytes: white where the picture is, black around it.
    w, h = expect
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout
    assert len(raw) == w * h
    def px(x, y):
        return raw[y * w + x]
    assert px(w // 2, h // 2) > 200          # the middle is the picture
    assert px(2, 2) < 40 and px(w - 3, h - 3) < 40   # the corners are black
    pw, ph = (int(n) for n in size.split("x"))
    # The picture's own size, counted along the middle row and column.
    assert abs(sum(1 for x in range(w) if px(x, h // 2) > 128) - pw) <= 2
    assert abs(sum(1 for y in range(h) if px(w // 2, y) > 128) - ph) <= 2
