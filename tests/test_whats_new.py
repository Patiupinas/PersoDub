"""GET /api/whats-new: the bundled release notes the update popup shows."""
import re

from fastapi.testclient import TestClient

from app.api import misc as misc_api
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_whats_new_returns_version_and_notes():
    r = client.get("/api/whats-new")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["version"], str)
    assert isinstance(body["notes"], list) and body["notes"]
    assert all(isinstance(n, str) for n in body["notes"])


def test_whats_new_speaks_the_engines_language():
    """A Korean engine reads the Korean notes, an English one the English; both
    lists are the same length, so a release cannot forget one language's notes."""
    from app import i18n
    before = i18n.current_language()
    try:
        i18n.set_language("ko")
        ko = client.get("/api/whats-new").json()["notes"]
        i18n.set_language("en")
        en = client.get("/api/whats-new").json()["notes"]
    finally:
        i18n.set_language(before)
    assert ko and en and ko != en
    assert len(ko) == len(en)
    assert all(re.search("[가-힣]", n) for n in ko), "the Korean notes are Korean"
    assert not any(re.search("[가-힣]", n) for n in en), "the English notes are English"


def test_whats_new_survives_a_missing_file(monkeypatch, tmp_path):
    import os
    real_join = os.path.join

    def fake_join(*parts):
        p = real_join(*parts)
        return str(tmp_path / "gone.json") if p.endswith("whats_new.json") else p

    monkeypatch.setattr(misc_api.os.path, "join", fake_join)
    r = client.get("/api/whats-new")
    assert r.status_code == 200
    assert r.json()["notes"] == []
