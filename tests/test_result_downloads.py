"""Result downloads: original.mp4 / dubbed_<lang>.mp4 / dubbed_<lang>.srt."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import engines_status, state
from app.api import dub as dub_api
from app.main import app
from tests.marks import needs_ffmpeg


@pytest.fixture(autouse=True)
def _models_ready(monkeypatch):
    # Model files live in a kit these tests never build -- the 409
    # preflight is exercised in tests/test_dub_start_preflight.py.
    from app.api import _launch as launch_api
    monkeypatch.setattr(launch_api, "missing_models", lambda *a, **kw: [])

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture(autouse=True)
def _all_engines_available(monkeypatch):
    for name in ("gemma_available", "qwen_available", "gemini_available", "perso_available"):
        monkeypatch.setattr(engines_status, name, lambda: True)
    monkeypatch.setattr(engines_status, "gemma_status", lambda: "available")
    monkeypatch.setattr(engines_status, "hunyuan_status", lambda: "available")
    monkeypatch.setattr(engines_status, "qwen_status", lambda: "available")


def _finished_job(monkeypatch, target="en"):
    """Start a real upload job whose pipeline is faked, and wait for it."""
    def fake_run_dub(**kw):
        work = os.path.dirname(kw["out_path"])
        with open(kw["out_path"], "wb") as f:
            f.write(b"FAKEDUB")
        with open(os.path.join(work, "translated.srt"), "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
        return {"job_id": "x", "out_path": kw["out_path"], "num_segments": 1,
                "auto_translated": True}

    monkeypatch.setattr(dub_api, "run_dub", fake_run_dub)
    r = client.post("/api/dub/start",
                    data={"language_code": target},
                    files={"video": ("v.mp4", b"FAKEMP4", "video/mp4")})
    jid = r.json()["job_id"]
    deadline = time.time() + 5
    while time.time() < deadline:
        if client.get(f"/api/dub/jobs/{jid}").json()["status"] == "done":
            return jid
        time.sleep(0.02)
    raise AssertionError("job never finished")


def test_dub_download_is_named_for_the_target_language(monkeypatch):
    jid = _finished_job(monkeypatch, target="ko")
    r = client.get(f"/api/dub/result/{jid}")
    assert r.status_code == 200
    assert 'filename="dub_ko.mp4"' in r.headers["content-disposition"]


def test_original_is_downloadable_for_a_link_job(monkeypatch):
    # _finished_job posts an uploaded file; stamping from_link makes the job
    # look like one that pulled its video from a URL, which is the only case
    # where the original is handed back.
    # state.job_store, not `from app.state import job_store`: the store is a
    # module attribute other tests reassign, and a name bound at import time
    # would keep pointing at whichever object existed then.
    jid = _finished_job(monkeypatch)
    state.job_store._update(jid, from_link=True)

    r = client.get(f"/api/dub/result/{jid}/original")
    assert r.status_code == 200
    assert r.content == b"FAKEMP4"
    assert 'filename="org.mp4"' in r.headers["content-disposition"]

    # The URL the Download original button actually points at, so the gate
    # cannot be inverted without a test noticing.
    d = client.get(f"/api/dub/result/{jid}/original?download=1")
    assert d.status_code == 200
    assert d.content == b"FAKEMP4"


def test_original_download_is_refused_for_an_uploaded_file(monkeypatch):
    # The screens play an uploaded original freely (the running screen blurs it
    # behind the progress card), but the Download original button stays link-
    # only: the user already has the file they uploaded.
    jid = _finished_job(monkeypatch)
    assert client.get(f"/api/dub/result/{jid}/original").status_code == 200
    assert client.get(f"/api/dub/result/{jid}/original?download=1").status_code == 404


def test_original_404s_when_the_job_is_unknown():
    assert client.get("/api/dub/result/nope/original").status_code == 404


def test_srt_download_has_a_filename(monkeypatch):
    jid = _finished_job(monkeypatch, target="ja")
    r = client.get(f"/api/dub/result/{jid}/srt?download=1")
    assert r.status_code == 200
    assert 'filename="dub_ja.srt"' in r.headers["content-disposition"]


def test_srt_viewer_response_is_unchanged(monkeypatch):
    # The in-app subtitle viewer fetches this without ?download -- it must keep
    # returning plain text with no attachment header.
    jid = _finished_job(monkeypatch)
    r = client.get(f"/api/dub/result/{jid}/srt")
    assert r.status_code == 200
    assert "content-disposition" not in {k.lower() for k in r.headers}
    assert "hello" in r.text


# --- Audio only: the dub's sound as mp3 or wav ------------------------------

def _fake_ffmpeg(monkeypatch):
    from app import media
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"SOUND")
        class R:
            returncode = 0
            stderr = ""
        return R()
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    return calls


def test_audio_only_is_the_dubs_sound_named_for_the_language(monkeypatch):
    jid = _finished_job(monkeypatch, target="ko")
    calls = _fake_ffmpeg(monkeypatch)
    r = client.get(f"/api/dub/result/{jid}/audio?format=mp3&download=1")
    assert r.status_code == 200 and r.content == b"SOUND"
    assert 'filename="dub_ko.mp3"' in r.headers["content-disposition"]
    assert calls[-1][calls[-1].index("-c:a") + 1] == "libmp3lame"
    # Built once: the second ask is served from the job's folder.
    client.get(f"/api/dub/result/{jid}/audio?format=mp3&download=1")
    assert len(calls) == 1
    r = client.get(f"/api/dub/result/{jid}/audio?format=wav&download=1")
    assert 'filename="dub_ko.wav"' in r.headers["content-disposition"]
    assert calls[-1][calls[-1].index("-c:a") + 1] == "pcm_s16le"


def test_audio_only_is_made_again_after_the_video_is(monkeypatch):
    jid = _finished_job(monkeypatch)
    calls = _fake_ffmpeg(monkeypatch)
    client.get(f"/api/dub/result/{jid}/audio")
    out = state.job_store.get(jid)["result"]["out_path"]
    later = time.time() + 60
    os.utime(out, (later, later))
    client.get(f"/api/dub/result/{jid}/audio")
    assert len(calls) == 2


def test_audio_only_refuses_another_format_and_an_unknown_job(monkeypatch):
    jid = _finished_job(monkeypatch)
    assert client.get(f"/api/dub/result/{jid}/audio?format=ogg").status_code == 422
    assert client.get("/api/dub/result/nope/audio").status_code == 404


# ---- the original's voice and background, out of the job's folder ----

def _with_stems(jid, *names):
    """A second of real silence under each name the separation stage writes."""
    import subprocess
    work = state.job_store.get(jid)["work_dir"]
    for name in names:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=stereo", "-t", "1", os.path.join(work, name)],
                       check=True)
    return work


@needs_ffmpeg
def test_voice_and_background_go_out_as_mp3_or_wav_named_for_the_project(monkeypatch):
    jid = _finished_job(monkeypatch)
    work = _with_stems(jid, "vocals.wav", "background.wav")
    project = state.job_store.get(jid)["project"]
    assert client.get(f"/api/dub/result/{jid}/stems").json() == {"voice": True, "background": True}
    for which in ("voice", "background"):
        r = client.get(f"/api/dub/result/{jid}/stem/{which}?format=mp3")
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/mpeg"
        assert f"{project}_{which}.mp3" in r.headers["content-disposition"]
        assert os.path.exists(os.path.join(work, f"stem-{which}.mp3"))
        r = client.get(f"/api/dub/result/{jid}/stem/{which}?format=wav")
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert r.content[:4] == b"RIFF"
        assert f"{project}_{which}.wav" in r.headers["content-disposition"]


@needs_ffmpeg
def test_a_missing_stem_is_404_and_the_list_says_which_is_there(monkeypatch):
    jid = _finished_job(monkeypatch)
    _with_stems(jid, "background.wav")
    assert client.get(f"/api/dub/result/{jid}/stems").json() == {"voice": False, "background": True}
    assert client.get(f"/api/dub/result/{jid}/stem/voice").status_code == 404
    assert client.get(f"/api/dub/result/{jid}/stem/background").status_code == 200
    assert client.get(f"/api/dub/result/{jid}/stem/drums").status_code == 404
    assert client.get(f"/api/dub/result/{jid}/stem/background?format=ogg").status_code == 422
    assert client.get("/api/dub/result/nope/stem/voice").status_code == 404
    assert client.get("/api/dub/result/nope/stems").status_code == 404


@needs_ffmpeg
def test_stems_are_refused_for_a_job_that_is_not_a_dubbing(monkeypatch):
    jid = _finished_job(monkeypatch)
    _with_stems(jid, "vocals.wav", "background.wav")
    state.job_store._update(jid, kind="erase")
    assert client.get(f"/api/dub/result/{jid}/stems").status_code == 409
    assert client.get(f"/api/dub/result/{jid}/stem/voice").status_code == 409
