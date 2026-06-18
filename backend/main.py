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


@app.get("/")
async def root():
    return {
        "service": "StripWall",
        "usage": "GET /fetch?url=https://example.com/article",
        "version": "1.0.0",
    }


# ── Health check for Android app connectivity test ──────────────────────
@app.get("/ping")
async def ping():
    return {"pong": True}
