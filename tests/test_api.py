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


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model"] == "qwen/qwen3.8-27b"


def test_generate_no_image_returns_400():
    r = client.post("/api/generate", files={}, data={"api_key": "gsk_test"})
    assert r.status_code == 400


def test_generate_bad_type_returns_400():
    r = client.post(
        "/api/generate",
        files={"image": ("evil.txt", b"hello world", "text/plain")},
        data={"api_key": "gsk_test"},
    )
    assert r.status_code == 400


def test_generate_corrupt_image_returns_400():
    r = client.post(
        "/api/generate",
        files={"image": ("shot.png", b"not a real image bytes", "image/png")},
        data={"api_key": "gsk_test"},
    )
    assert r.status_code == 400


def test_generate_oversized_returns_400():
    big = b"\xff" * (10 * 1024 * 1024 + 1)
    r = client.post(
        "/api/generate",
        files={"image": ("big.png", big, "image/png")},
        data={"api_key": "gsk_test"},
    )
    assert r.status_code == 400


def test_generate_no_key_returns_401(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_TEST_KEY", raising=False)
    png = make_png()
    r = client.post("/api/generate", files={"image": ("s.png", png, "image/png")}, data={})
    assert r.status_code == 401


def test_generate_fake_key_returns_auth_error(monkeypatch):
    class AuthenticationError(Exception):
        status_code = 401

    def fake_call(api_key, data_uri, style_hint):
        raise AuthenticationError("invalid api key")

    monkeypatch.setattr(appmod, "call_vision", fake_call)
    png = make_png()
    r = client.post(
        "/api/generate",
        files={"image": ("s.png", png, "image/png")},
        data={"api_key": "gsk_fake_key_123"},
    )
    assert r.status_code == 401


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
