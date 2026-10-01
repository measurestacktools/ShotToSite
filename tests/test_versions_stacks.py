import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as appmod

client = TestClient(appmod.app)


def make_png(color=(30, 60, 120), size=(200, 150)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    appmod.clear_versions()
    monkeypatch.setattr(appmod, "_session_key", "gsk_test_server_key")
    yield
    appmod.clear_versions()


HTML_A = "```html\n<html><body><h1>A</h1></body></html>\n```"
HTML_B = "```html\n<html><body><h1>B</h1></body></html>\n```"
JSX_A = "```jsx\nexport default function App() { return (<div className=\"p-4\">Hi</div>); }\n```"


def test_versions_empty():
    r = client.get("/api/versions")
    assert r.status_code == 200
    assert r.json() == {"versions": []}


def test_generate_creates_version_and_metadata_has_no_html(monkeypatch):
    monkeypatch.setattr(appmod, "call_vision", lambda *a, **k: HTML_A)
    png = make_png()
    r = client.post(
        "/api/generate",
        files={"image": ("s.png", png, "image/png")},
        data={"stack": "html-css", "style_hint": "rounded cards"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stack"] == "html-css"
    assert body["version_id"]

    r2 = client.get("/api/versions")
    assert r2.status_code == 200
    versions = r2.json()["versions"]
    assert len(versions) == 1
    meta = versions[0]
    assert "html" not in meta
    assert meta["id"] == body["version_id"]
    assert meta["stack"] == "html-css"
    assert meta["prompt"] == "rounded cards"
    assert meta["current"] is True

    r3 = client.get(f"/api/versions/{body['version_id']}")
    assert r3.status_code == 200
    assert "<h1>A</h1>" in r3.json()["html"]


def test_generate_default_stack_backward_compat(monkeypatch):
    monkeypatch.setattr(appmod, "call_vision", lambda *a, **k: HTML_A)
    png = make_png()
    r = client.post("/api/generate", files={"image": ("s.png", png, "image/png")})
    assert r.status_code == 200
    assert r.json()["stack"] == "html"


def test_generate_invalid_stack_normalizes_to_html(monkeypatch):
    seen = {}

    def fake_call(api_key, data_uri, style_hint, stack=None):
        seen["stack"] = stack
        return HTML_A

    monkeypatch.setattr(appmod, "call_vision", fake_call)
    png = make_png()
    r = client.post(
        "/api/generate",
        files={"image": ("s.png", png, "image/png")},
        data={"stack": "vue-svelte-quantum"},
    )
    assert r.status_code == 200
    assert r.json()["stack"] == "html"
    assert seen["stack"] in (None, "html", "vue-svelte-quantum")


def test_generate_react_stack_returns_jsx(monkeypatch):
    monkeypatch.setattr(appmod, "call_vision", lambda *a, **k: JSX_A)
    png = make_png()
    r = client.post(
        "/api/generate",
        files={"image": ("s.png", png, "image/png")},
        data={"stack": "react"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stack"] == "react"
    assert "function App" in body["html"]


def test_refine_legacy_flow_creates_version_and_sends_previous_html(monkeypatch):
    monkeypatch.setattr(appmod, "call_vision", lambda *a, **k: HTML_A)
    png = make_png()
    g = client.post("/api/generate", files={"image": ("s.png", png, "image/png")})
    assert g.status_code == 200
    first_id = g.json()["version_id"]

    captured = {}

    def fake_refine(api_key, html, instruction, stack=None):
        captured["html"] = html
        captured["instruction"] = instruction
        return HTML_B

    monkeypatch.setattr(appmod, "call_refine", fake_refine)
    # legacy body: no stack key — must keep working
    r = client.post("/api/refine", json={"html": "<html>prev</html>", "instruction": "make hero dark"})
    assert r.status_code == 200
    assert r.json()["stack"] == "html"
    assert captured["html"] == "<html>prev</html>"
    assert captured["instruction"] == "make hero dark"

    versions = client.get("/api/versions").json()["versions"]
    assert len(versions) == 2
    assert versions[-1]["label"] == "Refine"
    assert versions[-1]["current"] is True
    assert versions[0]["id"] == first_id
    assert versions[0]["current"] is False


def test_restore_makes_version_current(monkeypatch):
    monkeypatch.setattr(appmod, "call_vision", lambda *a, **k: HTML_A)
    png = make_png()
    g1 = client.post("/api/generate", files={"image": ("s.png", png, "image/png")})
    monkeypatch.setattr(appmod, "call_vision", lambda *a, **k: HTML_B)
    g2 = client.post("/api/generate", files={"image": ("s.png", png, "image/png")})
    id1, id2 = g1.json()["version_id"], g2.json()["version_id"]
    assert id1 != id2

    r = client.post(f"/api/versions/{id1}/restore")
    assert r.status_code == 200
    assert "<h1>A</h1>" in r.json()["html"]

    versions = {v["id"]: v for v in client.get("/api/versions").json()["versions"]}
    assert versions[id1]["current"] is True
    assert versions[id2]["current"] is False


def test_version_404s():
    assert client.get("/api/versions/does-not-exist").status_code == 404
    assert client.post("/api/versions/does-not-exist/restore").status_code == 404


def test_versions_cap_20():
    for i in range(25):
        appmod.add_version(label=f"Generate #{i}", html=f"<html>{i}</html>", prompt="", stack="html")
    versions = client.get("/api/versions").json()["versions"]
    assert len(versions) == 20
    # oldest evicted, newest kept
    assert versions[0]["label"] == "Generate #5"
    assert versions[-1]["label"] == "Generate #24"
