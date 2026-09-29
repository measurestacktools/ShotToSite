import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from PIL import Image

import app as appmod

client = TestClient(appmod.app)


def make_png(color=(30, 60, 120), size=(400, 300)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def _clear_key(monkeypatch):
    monkeypatch.setattr(appmod, "_session_key", None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_TEST_KEY", raising=False)


def _set_server_key(monkeypatch, key="gsk_test_server_key"):
    monkeypatch.setattr(appmod, "_session_key", key)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model"] == "qwen/qwen3.8-27b"


def test_generate_no_image_returns_400(monkeypatch):
    _set_server_key(monkeypatch)
    r = client.post("/api/generate", files={})
    assert r.status_code == 400


def test_generate_bad_type_returns_400(monkeypatch):
    _set_server_key(monkeypatch)
    r = client.post(
        "/api/generate",
        files={"image": ("evil.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 400


def test_generate_corrupt_image_returns_400(monkeypatch):
    _set_server_key(monkeypatch)
    r = client.post(
        "/api/generate",
        files={"image": ("shot.png", b"not a real image bytes", "image/png")},
    )
    assert r.status_code == 400


def test_generate_oversized_returns_400(monkeypatch):
    _set_server_key(monkeypatch)
    big = b"\xff" * (10 * 1024 * 1024 + 1)
    r = client.post(
        "/api/generate",
        files={"image": ("big.png", big, "image/png")},
    )
    assert r.status_code == 400


def test_generate_no_key_returns_401(monkeypatch):
    _clear_key(monkeypatch)
    png = make_png()
    r = client.post("/api/generate", files={"image": ("s.png", png, "image/png")}, data={})
    assert r.status_code == 401


def test_generate_client_key_ignored_returns_401(monkeypatch):
    # Per-request client keys are no longer accepted; server memory/env only.
    _clear_key(monkeypatch)
    png = make_png()
    r = client.post(
        "/api/generate",
        files={"image": ("s.png", png, "image/png")},
        data={"api_key": "gsk_client_should_be_ignored"},
        headers={"X-Groq-Key": "gsk_client_should_be_ignored"},
    )
    assert r.status_code == 401


def test_generate_fake_key_returns_auth_error(monkeypatch):
    class AuthenticationError(Exception):
        status_code = 401

    def fake_call(api_key, data_uri, style_hint):
        raise AuthenticationError("invalid api key")

    monkeypatch.setattr(appmod, "call_vision", fake_call)
    _set_server_key(monkeypatch, "gsk_fake_key_123")
    png = make_png()
    r = client.post(
        "/api/generate",
        files={"image": ("s.png", png, "image/png")},
    )
    assert r.status_code == 401


def test_set_key_empty_returns_400(monkeypatch):
    _clear_key(monkeypatch)
    r = client.post("/api/key", json={"key": ""})
    assert r.status_code == 400
    assert appmod._session_key is None


def test_set_key_fake_returns_401_not_saved(monkeypatch):
    class AuthenticationError(Exception):
        status_code = 401

    class FakeModels:
        def list(self):
            raise AuthenticationError("invalid api key")

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(appmod, "make_client", lambda key: FakeClient())
    _clear_key(monkeypatch)
    r = client.post("/api/key", json={"key": "gsk_fake_key_123"})
    assert r.status_code == 401
    assert appmod._session_key is None


def test_delete_key_returns_200(monkeypatch):
    monkeypatch.setattr(appmod, "_session_key", "gsk_something")
    r = client.delete("/api/key")
    assert r.status_code == 200
    assert appmod._session_key is None


def test_status_reports_source_not_key_material(monkeypatch):
    _set_server_key(monkeypatch, "gsk_secret_xyz")
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["has_key"] is True
    assert body["source"] == "server-memory"
    assert "gsk_secret_xyz" not in r.text


def test_extract_html_fence():
    raw = 'here ```html\n<html><body><h1>Hi</h1></body></html>\n``` done'
    assert appmod.extract_html(raw).strip().startswith("<html>")


def test_extract_html_raw_fallback():
    raw = "<html><body>plain</body></html>"
    assert appmod.extract_html(raw) is not None
    assert appmod.extract_html("just some prose, no tags") is None


def test_validate_downscale():
    png = make_png(size=(3000, 2000))
    uri, w, h = appmod.validate_and_downscale(png, "s.png", "image/png")
    assert uri.startswith("data:image/")
    assert max(w, h) <= 1280
