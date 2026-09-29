# ShotToSite — Screenshot → Website

Upload a screenshot, get an **inspired recreation** as a single self-contained HTML file. Never pixel-perfect by design.

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
- `GET /api/status` → `{has_key, model}`
- `POST /api/verify` `{api_key}` → verifies via `models.list`
- `POST /api/generate` multipart `image` (JPG/PNG/WEBP/GIF ≤10MB) + `style_hint?` + `api_key?` → `{html}`
- `POST /api/refine` JSON `{html, instruction, api_key?}` → `{html}`

Key resolution: explicit `api_key` → `X-Groq-Key` header → `Authorization: Bearer` → `GROQ_API_KEY` → `GROQ_TEST_KEY` env.

## Safety
- Uploads are Pillow-validated, downscaled server-side (longest side 1280px), never executed.
- Generated HTML is rendered **only** in `<iframe sandbox="allow-scripts" srcdoc="…">`.
- Code fence extraction is defensive (```html blocks, else raw-HTML fallback, else 502 error).

## Limitations
- Inspired recreation, not pixel-perfect; text in screenshots may be paraphrased.
- Vision quality depends on Groq model availability (`qwen/qwen3.8-27b`).
- GIF uses first frame; very complex layouts may simplify on mobile.
