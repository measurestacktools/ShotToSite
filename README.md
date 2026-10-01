# ShotToSite — Screenshot → Website

Upload a screenshot, get an **inspired recreation** as a single self-contained HTML file. Never pixel-perfect by design.

## Features
- Drag-drop screenshot upload with preview (JPG/PNG/WEBP/GIF ≤10MB)
- AI-generated responsive HTML/CSS/JS, sandboxed live preview, code view
- Copy, download `.html`, refine with instructions ("make it mobile", "change colors")

## Requirements
- Python 3.10+
- A free Groq API key ([console.groq.com/keys](https://console.groq.com/keys))
- Internet (AI calls go to Groq)

## Installation
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## How to use
1. Add your key via Settings (verified instantly) or `.env`
2. Drop a screenshot → **Generate** → watch the live preview
3. Switch to **Code**, copy/download, or **Refine** with instructions

## Stack
Python + FastAPI + vanilla HTML/CSS/JS. OpenAI SDK pointed at `https://api.groq.com/openai/v1`, vision model `qwen/qwen3.8-27b`.

## Run
```bash
pip install -r requirements.txt
copy .env.example .env   # add GROQ_API_KEY
uvicorn app:app --port 8005
```
Open http://127.0.0.1:8005

## API
- `GET /api/status` → `{has_key, model, source}` (presence/source only, never key material)
- `POST /api/key` `{key}` → verifies via `models.list`, stores in server process memory only
- `DELETE /api/key` → clears the server-memory key
- `POST /api/generate` multipart `image` (JPG/PNG/WEBP/GIF ≤10MB) + `style_hint?` → `{html}`
- `POST /api/refine` JSON `{html, instruction}` → `{html}`

Key resolution: server-memory key (set via `POST /api/key`) → `GROQ_API_KEY` → `GROQ_TEST_KEY` env. Per-request client keys (multipart/header/JSON) are NOT accepted. The browser never stores or re-sends the key.

## Safety
- Uploads are Pillow-validated, downscaled server-side (longest side 1280px), never executed.
- Generated HTML is rendered **only** in `<iframe sandbox="allow-scripts" srcdoc="…">`.
- Code fence extraction is defensive (```html blocks, else raw-HTML fallback, else 502 error).

## Limitations
- Inspired recreation, not pixel-perfect; text in screenshots may be paraphrased.
- Vision quality depends on Groq model availability (`qwen/qwen3.8-27b`).
- GIF uses first frame; very complex layouts may simplify on mobile.
