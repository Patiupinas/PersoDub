"""The Dub Agent's queue_dub and the screen's dub start must speak the same form.

app/mcp_server.py's queue_dub starts a dubbing by posting a multipart form to
POST /api/dub/start, which app/api/dub.py's dub_start reads. Nothing ties the
two together but the field names: FastAPI drops a form field that no
parameter takes, without a word. So a field renamed on either side would not
fail -- the dubbing would start without it (a local dub without dub_mode went
to Perso and spent credits, Windows F10, 2026-10-07).

The names checked here are the ones queue_dub really posts: it is run with its
HTTP layer faked and the form it sends is captured, once for a dub on this
computer and once for a Perso dub, each with every optional choice named.
"""
import inspect

import pytest
from fastapi import params

import app.mcp_server as mcp_server
from app import languages
from app.api import dub as dub_api


class _Answer:
    def __init__(self, body):
        self.status_code = 200
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


# Every optional argument named, so every branch that adds a field runs.
DUBS = {
    "local": {"target_language": "ko", "dub_mode": "local", "source_language": "en", "num_speakers": 2,
              "translator": "hunyuan", "stt": "local", "separation": "local", "voice": "qwen3"},
    "perso": {"target_language": "ko", "dub_mode": "perso", "source_language": "en", "num_speakers": 2,
              "perso_model": "wren"},
}


@pytest.fixture
def posted_form(monkeypatch, tmp_path):
    """posted_form(**queue_dub_args) -> {"data": [...], "files": [...]}: the
    field names of the one form queue_dub posted to /api/dub/start."""
    # The user had the plan in an earlier reply, so confirm=true goes through
    # (the same stand-in as tests/test_mcp_server.py's _new_reply).
    monkeypatch.setattr(mcp_server, "_asked", {})
    monkeypatch.setattr(mcp_server, "_ASK_FILE", str(tmp_path / "asked.json"))
    mcp_server._write_asks({"queue_dub": {"plan": "*", "pid": 0}})
    monkeypatch.setattr(languages, "_fetch", lambda: None)   # Perso's language list: the bundled copy
    # A local dub reads the saved defaults first (which stages are paid).
    monkeypatch.setattr(mcp_server.httpx, "get", lambda url, **kw: _Answer({"defaults": {}}))
    forms = []

    def fake_post(url, data=None, files=None, **kw):
        forms.append({"url": url, "data": sorted(data or {}), "files": sorted(files or {})})
        return _Answer({"job_id": "j1", "status": "queued"})

    monkeypatch.setattr(mcp_server.httpx, "post", fake_post)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    def run(**kw):
        assert mcp_server.queue_dub(str(video), confirm=True, **kw) == {"job_id": "j1", "status": "queued"}
        assert [f["url"] for f in forms] == [mcp_server.API + "/api/dub/start"]
        return forms[0]

    return run


@pytest.mark.parametrize("mode", sorted(DUBS))
def test_every_field_queue_dub_posts_is_a_dub_start_parameter(posted_form, mode):
    form = posted_form(**DUBS[mode])
    accepted = inspect.signature(dub_api.dub_start).parameters
    for name in form["data"] + form["files"]:
        assert name in accepted, (
            "queue_dub (app/mcp_server.py) posts the field %r, but dub_start (app/api/dub.py) "
            "has no parameter of that name: FastAPI would drop it silently. Rename one side "
            "to match the other." % name)
    # A text field must land on a Form parameter and the upload on a File one:
    # a field read from anywhere else is dropped the same silent way.
    files = {n for n, p in accepted.items() if isinstance(p.default, params.File)}
    forms = {n for n, p in accepted.items() if isinstance(p.default, params.Form)} - files
    assert set(form["data"]) <= forms, "posted as text, not a Form parameter: %s" % (set(form["data"]) - forms)
    assert set(form["files"]) <= files, "posted as a file, not a File parameter: %s" % (set(form["files"]) - files)


# The check above covers only the fields the two calls reach. These are the
# names each one posts today, so a field that stops being sent, or a new one
# that is always sent, changes this table on purpose. A new optional argument
# has to be named in DUBS too, or the check above never sees its field.
POSTED = {
    "local": {"data": ["dub_mode", "language", "language_code", "num_speakers", "sep_engine",
                       "source_language_code", "stt_engine", "translate_engine", "tts_engine"],
              "files": ["video"]},
    "perso": {"data": ["dub_mode", "language", "language_code", "num_speakers", "perso_model",
                       "source_language_code"],
              "files": ["video"]},
}


@pytest.mark.parametrize("mode", sorted(DUBS))
def test_the_dubs_above_reach_every_field_queue_dub_sends(posted_form, mode):
    form = posted_form(**DUBS[mode])
    assert {"data": form["data"], "files": form["files"]} == POSTED[mode]
