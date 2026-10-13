"""The page's ES modules and the page itself are served with a per-launch token
on every module URL and Cache-Control: no-cache -- the first launch after an
update must never run the new page against a module a browser cached from the
version before (2026-09-07: a cached modelsUi.mjs lacked a new export, and every
button on the page was dead). Its stylesheets (static/css) are no-cache too."""
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_the_page_stamps_every_module_import_with_the_launch_token():
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    token = main_module.ASSET_TOKEN
    # The page loads its script, ui/src/app.mjs; the script imports the rest.
    assert f'from "/js/app.mjs?v={token}"' in r.text
    assert 'from "/js/' not in r.text.replace(f"?v={token}", "")  or all(
        f"?v={token}" in line for line in r.text.splitlines() if 'from "/js/' in line)
    script = client.get(f"/js/app.mjs?v={token}").text
    assert f'from "./dubApi.mjs?v={token}"' in script
    assert all(f"?v={token}" in line for line in script.splitlines() if 'from "./' in line)


def test_a_module_is_served_uncacheable_with_its_own_imports_stamped():
    token = main_module.ASSET_TOKEN
    r = client.get(f"/js/modelsDialog.mjs?v={token}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-cache"
    assert f'from "./modelsUi.mjs?v={token}"' in r.text
    # The token holds for the life of the process: one page, one set of URLs.
    page = client.get("/").text + client.get(f"/js/app.mjs?v={token}").text
    assert page.count(f"?v={token}") >= 10


def test_only_named_modules_in_ui_src_are_served():
    assert client.get("/js/nope.mjs").status_code == 404
    assert client.get("/js/..%2Fdub_api.py").status_code == 404
    assert client.get("/js/modelsUi.mjs.bak").status_code == 404


def test_the_stylesheets_the_page_links_are_served_uncacheable():
    page = client.get("/").text
    for name in ("app.css", "agent.css"):
        assert f'<link rel="stylesheet" href="/css/{name}">' in page
        r = client.get(f"/css/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/css")
        assert r.headers["cache-control"] == "no-cache"


def test_only_named_stylesheets_in_static_css_are_served():
    assert client.get("/css/nope.css").status_code == 404
    assert client.get("/css/..%2Findex.html").status_code == 404
    assert client.get("/css/App.css").status_code == 404
    assert client.get("/css/app.css.bak").status_code == 404
