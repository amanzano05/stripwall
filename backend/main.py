"""StripWall backend — fetch a URL, strip paywalls/overlays, return clean HTML."""

import re
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from stripper import strip_page

app = FastAPI(title="StripWall", version="1.0.0")

# ── CORS: allow the Android app to hit us from anywhere ──────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── User-agent rotation ──────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

# ── Blocked domains that reliably block bots even after stripping ────────
BLOCKED_DOMAINS = [
    "twitter.com", "x.com",
    "facebook.com", "instagram.com",
    "tiktok.com",
    "youtube.com",  # bot detection is aggressive
]


async def _fetch(url: str) -> tuple[str, str]:
    """Fetch a URL and return (html, final_url)."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    # Strip www.
    domain = re.sub(r"^www\.", "", domain)

    if any(blocked in domain for blocked in BLOCKED_DOMAINS):
        raise HTTPException(400, f"Domain {domain} is blocked — bot detection too aggressive.")

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=15.0,
        headers={
            "User-Agent": USER_AGENTS[uuid.uuid4().int % len(USER_AGENTS)],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            "Referer": "https://www.google.com/",
        },
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text, str(resp.url)


@app.get("/fetch")
async def fetch_url(url: str = Query(..., description="Target URL to fetch and strip")):
    """Fetch a URL, strip overlays/paywalls, return clean HTML."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc:
        raise HTTPException(400, "Invalid URL — no host detected.")

    try:
        raw_html, final_url = await _fetch(url)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Upstream returned {e.response.status_code}")
    except httpx.TimeoutException:
        raise HTTPException(504, "Upstream timed out")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Failed to fetch: {e}")

    try:
        clean = strip_page(raw_html, final_url)
    except Exception as e:
        raise HTTPException(500, f"Stripping failed: {e}")

    return HTMLResponse(content=clean)


# ── Root page: simple URL input for mobile ────────────────────────────
ROOT_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StripWall</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #121212; color: #E8EAED; display: flex;
    justify-content: center; align-items: center; min-height: 100vh; padding: 24px;
  }
  .card { background: #1E1E1E; border-radius: 16px; padding: 32px; max-width: 480px; width: 100%; }
  h1 { font-size: 24px; margin-bottom: 4px; color: #8AB4F8; }
  p.sub { color: #9AA0A6; font-size: 13px; margin-bottom: 20px; }
  form { display: flex; gap: 8px; }
  input {
    flex: 1; background: #0D1117; border: 1px solid #3D3D3D; border-radius: 10px;
    padding: 12px 16px; color: #E8EAED; font-size: 14px; outline: none;
  }
  input:focus { border-color: #8AB4F8; }
  input::placeholder { color: #5F6368; }
  button {
    background: #8AB4F8; color: #0D1117; border: none; border-radius: 10px;
    padding: 12px 20px; font-size: 14px; font-weight: 700; cursor: pointer;
  }
  button:hover { background: #9DC3FA; }
  .footer { margin-top: 20px; font-size: 12px; color: #5F6368; text-align: center; }
  .footer a { color: #8AB4F8; text-decoration: none; }
</style>
</head>
<body>
<div class="card">
  <h1>⚡ StripWall</h1>
  <p class="sub">Pega el URL de un artículo para leerlo sin paywall</p>
  <form action="/go" method="get">
    <input type="url" name="url" placeholder="https://ejemplo.com/articulo" required autofocus>
    <button type="submit">Go</button>
  </form>
  <div class="footer">O usá <a href="/bookmark">el bookmarklet</a> en desktop</div>
</div>
</body>
</html>"""


@app.get("/")
async def root():
    return HTMLResponse(content=ROOT_PAGE, status_code=200)


# ── Go redirect: /go?url=... → /fetch?url=... ────────────────────────
@app.get("/go")
async def go(url: str = Query(...)):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return RedirectResponse(url=f"/fetch?url={url}")


# ── Health check for Android app connectivity test ──────────────────────
@app.get("/ping")
async def ping():
    return {"pong": True}


# ── Bookmarklet installation page ──────────────────────────────────────
BOOKMARKLET_CODE = "javascript:location.href='https://stripwall.amago.fyi/fetch?url='+encodeURIComponent(location.href)"
BOOKMARKLET_PAGE = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StripWall — Bookmarklet</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #121212; color: #E8EAED; display: flex;
    justify-content: center; align-items: center; min-height: 100vh;
    padding: 24px;
  }}
  .card {{
    background: #1E1E1E; border-radius: 16px; padding: 32px;
    max-width: 480px; width: 100%; text-align: center;
  }}
  h1 {{ font-size: 24px; margin-bottom: 8px; color: #8AB4F8; }}
  p {{ color: #B0B0B0; font-size: 14px; line-height: 1.6; margin-bottom: 24px; }}
  a.bookmarklet {{
    display: inline-block; background: #8AB4F8; color: #0D1117;
    text-decoration: none; font-weight: 700; font-size: 16px;
    padding: 14px 32px; border-radius: 12px; margin-bottom: 24px;
  }}
  a.bookmarklet:hover {{ background: #9DC3FA; }}
  .steps {{ text-align: left; }}
  .step {{
    background: #2D2D2D; border-radius: 10px; padding: 12px 16px;
    margin-bottom: 10px; font-size: 13px; line-height: 1.5;
  }}
  .step strong {{ color: #8AB4F8; }}
  code {{
    background: #0D1117; color: #E8EAED; padding: 2px 6px;
    border-radius: 4px; font-size: 12px; word-break: break-all;
  }}
  .url-box {{
    background: #0D1117; border: 1px solid #3D3D3D; border-radius: 8px;
    padding: 12px; font-size: 11px; word-break: break-all;
    color: #9AA0A6; margin: 16px 0; user-select: all;
  }}
</style>
</head>
<body>
<div class="card">
  <h1>⚡ StripWall</h1>
  <p>Un click para leer cualquier artículo sin paywalls, popups ni overlays.</p>

  <a class="bookmarklet" href="{BOOKMARKLET_CODE}">📌 StripWall</a>

  <div class="steps">
    <div class="step"><strong>1.</strong> Arrastra el botón de arriba a tu barra de marcadores en desktop.<br><small>O copia el código abajo si estás en mobile.</small></div>
    <div class="step"><strong>2.</strong> Cuando estés en un artículo con paywall, toca el bookmarklet.</div>
    <div class="step"><strong>3.</strong> ¡Listo! El artículo se abre limpio en una pestaña.</div>
  </div>

  <div class="url-box">{BOOKMARKLET_CODE}</div>

  <p style="font-size:12px;color:#5F6368">
    Código: crea un bookmark y pega eso como URL.<br>
    Funciona en Chrome, Safari, Firefox, Samsung Internet.
  </p>
</div>
</body>
</html>"""


@app.get("/bookmark", response_class=HTMLResponse)
async def bookmark_page():
    return HTMLResponse(content=BOOKMARKLET_PAGE, status_code=200)
