"""ShotToSite — Screenshot to Website (inspired recreation, never pixel-perfect)."""
import base64
import io
import os
import re
import threading
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

load_dotenv()

MODEL = os.getenv("SHOT_TO_SITE_MODEL", "qwen/qwen3.8-27b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 1280
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="ShotToSite")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Groq API key lives ONLY in server process memory (or server env).
# It is NEVER accepted from browser storage / per-request client values.
_session_key: str | None = None


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL}


def resolve_api_key(explicit: str | None = None, header_key: str | None = None,
                    auth: str | None = None) -> str | None:
    # NOTE: client-supplied values (explicit/header/auth) are intentionally
    # ignored. Keys live only in server memory (_session_key) or server env.
    _ = (explicit, header_key, auth)
    if _session_key and _session_key.strip():
        return _session_key.strip()
    for env_name in ("GROQ_API_KEY", "GROQ_TEST_KEY"):
        v = os.getenv(env_name, "").strip()
        if v:
            return v
    return None


def key_source() -> str | None:
    if _session_key and _session_key.strip():
        return "server-memory"
    for env_name in ("GROQ_API_KEY", "GROQ_TEST_KEY"):
        if os.getenv(env_name, "").strip():
            return f"env:{env_name}"
    return None


def make_client(api_key: str):
    from openai import OpenAI
    return OpenAI(base_url=GROQ_BASE_URL, api_key=api_key)


def friendly_groq_error(e: Exception) -> tuple[int, str]:
    msg = str(e)
    status = getattr(e, "status_code", None)
    # openai lib error classes
    name = type(e).__name__
    if name == "AuthenticationError" or status == 401:
        return 401, "Groq rejected the API key (401). Open Settings and paste a valid Groq key."
    if name == "RateLimitError" or status == 429:
        return 429, "Groq rate limit hit (429). Wait a minute and try again."
    if name == "NotFoundError" or status == 404:
        return 404, f"Groq model not found (404): {MODEL}. The model id may be retired."
    if status == 503 or name in ("APIConnectionError", "ServiceUnavailableError"):
        return 503, "Groq is temporarily unavailable (503). Retry shortly."
    if name == "BadRequestError" or status == 400:
        if "image" in msg.lower():
            return 400, f"Groq rejected the image (400). Try a smaller/clearer JPG/PNG. Detail: {msg[:300]}"
        return 400, f"Groq bad request (400). Detail: {msg[:300]}"
    code = status if isinstance(status, int) and 400 <= status < 600 else 502
    return code, f"Groq request failed ({name}). Detail: {msg[:300]}"


def validate_and_downscale(raw: bytes, filename: str, content_type: str) -> tuple[str, int, int]:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"Unsupported file type '{ext or '?'}'. Use JPG, PNG, WEBP or GIF.")
    if content_type and content_type not in ALLOWED_MIME and content_type != "application/octet-stream":
        raise ValueError(f"Unsupported media type '{content_type}'. Use JPG, PNG, WEBP or GIF.")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Image too large ({len(raw)/1048576:.1f} MB). Max is 10 MB.")
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))  # reopen after verify
        # animated gif: take first frame
        if getattr(img, "is_animated", False):
            img.seek(0)
        img = img.convert("RGB") if img.mode in ("P", "RGBA", "LA") and ext in (".jpg", ".jpeg") else img.convert("RGB") if img.mode == "CMYK" else img
        w, h = img.size
        scale = min(1.0, MAX_SIDE / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            w, h = img.size
        buf = io.BytesIO()
        # keep transparency-friendly formats as PNG, else JPEG
        has_alpha = img.mode in ("RGBA", "LA")
        if has_alpha:
            img.save(buf, format="PNG")
            mime = "image/png"
        else:
            img.convert("RGB").save(buf, format="JPEG", quality=88)
            mime = "image/jpeg"
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:{mime};base64,{b64}", w, h
    except (UnidentifiedImageError, OSError):
        raise ValueError("File is not a valid image (corrupt or fake). Upload a real JPG/PNG/WEBP/GIF.")


def extract_html(text: str) -> str | None:
    if not text or not text.strip():
        return None
    # 1) fenced ```html ... ``` blocks (take longest)
    fences = re.findall(r"```(?:html)?\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidates = [c.strip() for c in fences if c.strip()]
    if candidates:
        best = max(candidates, key=len)
        if "<html" in best.lower() or "<!doctype" in best.lower() or ("<" in best and ">" in best):
            return best
    # 2) raw looks like full html doc
    t = text.strip()
    if "<!doctype" in t.lower() or "<html" in t.lower():
        # trim surrounding prose: find first <(!doctype|html) and last </html>
        m_start = re.search(r"<!(doctype)|<html", t, re.IGNORECASE)
        m_end = re.search(r"</html\s*>", t, re.IGNORECASE)
        if m_start:
            start = m_start.start()
            end = m_end.end() if m_end else len(t)
            return t[start:end].strip()
    # 3) fallback: raw contains html-ish tags and style
    if t.count("<") >= 3 and t.count(">") >= 3 and re.search(r"<(div|section|header|main|style|body|h1|p)\b", t, re.IGNORECASE):
        return t
    return None


GENERATE_SYSTEM = (
    "You are an expert front-end developer. Recreate the provided screenshot as a web page. "
    "This is an INSPIRED RECREATION, never claim pixel-perfect. "
    "Return ONE single self-contained HTML file with inline <style> and <script> only "
    "(no external CSS/JS files; CDN fonts ok but optional). "
    "Make it responsive (flex/grid + media queries, mobile-first), semantic, accessible. "
    "Output ONLY the HTML inside a single ```html fenced code block, no explanations."
)

REFINE_SYSTEM = (
    "You are an expert front-end developer editing a single self-contained HTML file. "
    "Apply the user's instruction to the provided HTML and return the FULL updated HTML file "
    "inside one ```html fenced block. Keep inline <style>/<script>, responsive. No explanations."
)

# --- Output stacks (stack param on /api/generate, backward-compatible default "html") ---
STACK_OUTPUT_INSTRUCTIONS = {
    "html": (
        "Return ONE single self-contained HTML file with inline <style> and <script> only "
        "(no external CSS/JS files, no Tailwind, no CDN dependencies; CDN fonts ok but optional). "
        "Make it responsive (flex/grid + media queries, mobile-first), semantic, accessible. "
        "Output ONLY the HTML inside a single ```html fenced code block, no explanations."
    ),
    "html-css": (
        "Return ONE single self-contained HTML file with semantic HTML and ONE separate "
        "<style> block in <head>. Use hand-written vanilla CSS only — NO Tailwind, NO utility "
        "classes, NO external CSS/JS or CDN links at all. Keep selectors clean, responsive "
        "(flex/grid + media queries, mobile-first), accessible. "
        "Output ONLY the HTML inside a single ```html fenced code block, no explanations."
    ),
    "tailwind": (
        "Return ONE single self-contained HTML file that styles primarily with Tailwind CSS "
        "via CDN (<script src=\"https://cdn.tailwindcss.com\"></script>) plus a minimal inline "
        "<style> block only where Tailwind cannot express something. Use Tailwind utility "
        "classes for layout/typography/spacing, responsive (md:/lg: prefixes), semantic, "
        "accessible. Output ONLY the HTML inside a single ```html fenced code block, no explanations."
    ),
    "react": (
        "Return ONE single React component as the default-export function App() using Tailwind "
        "utility classes for styling (assume Tailwind is already loaded; no imports beyond "
        "'react'). Keep it a single self-contained component, no external files, responsive, "
        "accessible. Output ONLY the component inside a single ```jsx fenced code block, "
        "no explanations, no surrounding HTML."
    ),
}
VALID_STACKS = set(STACK_OUTPUT_INSTRUCTIONS)

STACK_LABELS = {
    "html": "HTML",
    "html-css": "HTML+CSS",
    "tailwind": "HTML+Tailwind",
    "react": "React+Tailwind",
}


def normalize_stack(stack: str | None) -> str:
    s = (stack or "").strip().lower()
    return s if s in VALID_STACKS else "html"


def generate_system_for(stack: str | None) -> str:
    s = normalize_stack(stack)
    if s == "html":
        return GENERATE_SYSTEM
    return (
        "You are an expert front-end developer. Recreate the provided screenshot as a web page. "
        "This is an INSPIRED RECREATION, never claim pixel-perfect. "
        + STACK_OUTPUT_INSTRUCTIONS[s]
    )


def refine_system_for(stack: str | None) -> str:
    s = normalize_stack(stack) if stack else "html"
    if s == "html" or not stack:
        return REFINE_SYSTEM
    if s == "react":
        return (
            "You are an expert front-end developer editing a single React component (default "
            "export function App) styled with Tailwind utility classes. Apply the user's "
            "instruction and return the FULL updated component inside one ```jsx fenced block. "
            "No explanations, no surrounding HTML."
        )
    if s == "html-css":
        return (
            "You are an expert front-end developer editing a single self-contained HTML file "
            "styled with hand-written vanilla CSS in one <style> block (no Tailwind, no CDN). "
            "Apply the user's instruction and return the FULL updated HTML file inside one "
            "```html fenced block. No explanations."
        )
    # tailwind
    return (
        "You are an expert front-end developer editing a single self-contained HTML file styled "
        "primarily with Tailwind CSS via CDN plus minimal inline <style>. Apply the user's "
        "instruction and return the FULL updated HTML file inside one ```html fenced block. "
        "No explanations."
    )


def extract_react(text: str) -> str | None:
    if not text or not text.strip():
        return None
    fences = re.findall(r"```(?:jsx|tsx|js|javascript|html)?\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidates = [c.strip() for c in fences if c.strip()]
    if candidates:
        # prefer a block that looks like a component
        for best in sorted(candidates, key=len, reverse=True):
            if ("<" in best and ">" in best) and re.search(
                r"(function\s+App|default\s+export|const\s+App|return\s*\(|className=)", best
            ):
                return best
        best = max(candidates, key=len)
        if "<" in best and ">" in best:
            return best
    t = text.strip()
    if re.search(r"(function\s+App|default\s+export|const\s+App)", t) and "<" in t and ">" in t:
        return t
    return None


# --- Version history (additive, in-memory, cap 20) ---
_versions: list[dict] = []
_versions_lock = threading.Lock()
_version_seq = 0
_current_id: str | None = None
VERSION_CAP = 20


def add_version(label: str, html: str, prompt: str, stack: str) -> dict:
    global _version_seq, _current_id
    with _versions_lock:
        _version_seq += 1
        entry = {
            "id": f"v{_version_seq:03d}-{uuid.uuid4().hex[:6]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "html": html,
            "prompt": prompt or "",
            "stack": normalize_stack(stack),
        }
        _versions.append(entry)
        while len(_versions) > VERSION_CAP:
            _versions.pop(0)
        _current_id = entry["id"]
        return entry


def version_meta(v: dict) -> dict:
    return {
        "id": v["id"],
        "timestamp": v["timestamp"],
        "label": v["label"],
        "stack": v.get("stack", "html"),
        "prompt": v.get("prompt", ""),
        "current": v["id"] == _current_id,
    }


def find_version(vid: str) -> dict | None:
    with _versions_lock:
        for v in _versions:
            if v["id"] == vid:
                return v
    return None


def clear_versions() -> None:
    global _version_seq, _current_id
    with _versions_lock:
        _versions.clear()
        _version_seq = 0
        _current_id = None


def call_vision(api_key: str, data_uri: str, style_hint: str, stack: str | None = None) -> str:
    client = make_client(api_key)
    hint = f" Style hint: {style_hint.strip()}" if style_hint and style_hint.strip() else ""
    system = generate_system_for(stack)
    s = normalize_stack(stack)
    if s == "react":
        user_text = (
            "Recreate this screenshot as one self-contained React component (default export App, "
            f"Tailwind utilities, inspired recreation).{hint} Return only ```jsx ... ```."
        )
    else:
        user_text = (
            "Recreate this screenshot as one self-contained responsive HTML file "
            f"(inspired recreation).{hint} Return only ```html ... ```."
        )
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]},
        ],
        max_tokens=6000,
        temperature=0.6,
    )
    return resp.choices[0].message.content or ""


def call_refine(api_key: str, html: str, instruction: str, stack: str | None = None) -> str:
    client = make_client(api_key)
    system = refine_system_for(stack) if stack else REFINE_SYSTEM
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Instruction: {instruction}\n\nCurrent HTML:\n{html[:60000]}"},
        ],
        max_tokens=6000,
        temperature=0.5,
    )
    return resp.choices[0].message.content or ""


@app.get("/api/status")
def api_status():
    key = resolve_api_key()
    return {"has_key": bool(key), "model": MODEL, "base_url": GROQ_BASE_URL, "source": key_source()}


@app.post("/api/key")
def api_set_key(body: dict):
    global _session_key
    key = ""
    if isinstance(body, dict):
        key = (body.get("key") or "").strip()
    if not key:
        return JSONResponse({"ok": False, "error": "No API key provided."}, status_code=400)
    try:
        client = make_client(key)
        client.models.list()
    except Exception as e:  # noqa: BLE001
        code, msg = friendly_groq_error(e)
        return JSONResponse({"ok": False, "error": msg}, status_code=code)
    _session_key = key
    return {"ok": True}


@app.delete("/api/key")
def api_delete_key():
    global _session_key
    _session_key = None
    return {"ok": True}


@app.post("/api/verify")
def api_verify(body: dict):
    # Verify-only (does not store). New flow uses POST /api/key.
    raw = body if isinstance(body, dict) else {}
    key = (raw.get("key") or "").strip()
    if not key:
        return JSONResponse({"ok": False, "error": "No API key provided."}, status_code=400)
    try:
        client = make_client(key)
        client.models.list()
        return {"ok": True, "model": MODEL}
    except Exception as e:  # noqa: BLE001
        code, msg = friendly_groq_error(e)
        return JSONResponse({"ok": False, "error": msg}, status_code=code)


@app.post("/api/generate")
async def api_generate(
    request: Request,
    image: UploadFile | None = File(default=None),
    style_hint: str = Form(default=""),
    stack: str = Form(default="html"),
):
    key = resolve_api_key()
    if not key:
        return JSONResponse({"error": "No Groq API key. Open Settings and add one (or set GROQ_API_KEY in .env)."}, status_code=401)
    if image is None or not image.filename:
        return JSONResponse({"error": "No image uploaded. Drag-drop a JPG/PNG/WEBP/GIF screenshot."}, status_code=400)
    stack = normalize_stack(stack)
    raw = await image.read()
    if not raw:
        return JSONResponse({"error": "Empty file. Upload a real screenshot."}, status_code=400)
    try:
        data_uri, w, h = validate_and_downscale(raw, image.filename, image.content_type or "")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    try:
        out = call_vision(key, data_uri, style_hint, stack)
    except Exception as e:  # noqa: BLE001
        code, msg = friendly_groq_error(e)
        return JSONResponse({"error": msg}, status_code=code)
    if stack == "react":
        code_out = extract_react(out) or extract_html(out)
        err = "Model did not return a React component. Try a clearer screenshot or different style hint."
    else:
        code_out = extract_html(out)
        err = "Model did not return HTML. Try a clearer screenshot or different style hint."
    if not code_out:
        return JSONResponse({"error": err}, status_code=502)
    entry = add_version(
        label=f"Generate ({STACK_LABELS.get(stack, stack)})",
        html=code_out,
        prompt=(style_hint or "").strip(),
        stack=stack,
    )
    return {"html": code_out, "width": w, "height": h, "model": MODEL,
            "stack": stack, "version_id": entry["id"]}


@app.post("/api/refine")
async def api_refine(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body. Send {html, instruction}."}, status_code=400)
    key = resolve_api_key()
    if not key:
        return JSONResponse({"error": "No Groq API key. Open Settings and add one."}, status_code=401)
    html_in = (body.get("html") or "").strip()
    instruction = (body.get("instruction") or "").strip()
    # Optional stack passthrough (backward-compatible: absent/None => legacy HTML flow unchanged).
    raw_stack = body.get("stack", None)
    stack = normalize_stack(raw_stack) if raw_stack else None
    refine_stack = stack or "html"
    if not html_in:
        return JSONResponse({"error": "No HTML to refine. Generate a site first."}, status_code=400)
    if not instruction:
        return JSONResponse({"error": "Describe the change (e.g. 'make the hero dark blue')."}, status_code=400)
    try:
        # NOTE: previous html IS sent (fidelity): full current code + instruction.
        out = call_refine(key, html_in, instruction, stack)
    except Exception as e:  # noqa: BLE001
        code, msg = friendly_groq_error(e)
        return JSONResponse({"error": msg}, status_code=code)
    if refine_stack == "react":
        html = extract_react(out) or extract_html(out)
        err = "Model did not return a React component for the refinement. Try rephrasing."
    else:
        html = extract_html(out)
        err = "Model did not return HTML for the refinement. Try rephrasing."
    if not html:
        return JSONResponse({"error": err}, status_code=502)
    entry = add_version(label="Refine", html=html, prompt=instruction, stack=refine_stack)
    return {"html": html, "model": MODEL, "stack": refine_stack, "version_id": entry["id"]}


@app.get("/api/versions")
def api_versions():
    with _versions_lock:
        items = [version_meta(v) for v in _versions]
    return {"versions": items}


@app.get("/api/versions/{vid}")
def api_version_get(vid: str):
    v = find_version(vid)
    if not v:
        return JSONResponse({"error": "Version not found."}, status_code=404)
    return {
        "id": v["id"], "timestamp": v["timestamp"], "label": v["label"],
        "stack": v.get("stack", "html"), "prompt": v.get("prompt", ""),
        "html": v["html"], "current": v["id"] == _current_id,
    }


@app.post("/api/versions/{vid}/restore")
def api_version_restore(vid: str):
    global _current_id
    with _versions_lock:
        for v in _versions:
            if v["id"] == vid:
                _current_id = v["id"]
                return {
                    "html": v["html"], "stack": v.get("stack", "html"),
                    "version_id": v["id"], "label": v["label"],
                }
    return JSONResponse({"error": "Version not found."}, status_code=404)
