"""StripWall backend — fetch, proxy, strip, and interactive browse."""

import re
import uuid
from urllib.parse import urlparse, urljoin, quote

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

# ── Blocked domains ──────────────────────────────────────────────────────
BLOCKED_DOMAINS = [
    "twitter.com", "x.com",
    "facebook.com", "instagram.com",
    "tiktok.com",
    "youtube.com",
]


# ── Public URL for proxy link rewriting ─────────────────────────────
PUBLIC_URL = "https://stripwall.amago.fyi"


async def _fetch(url: str) -> tuple[str, str]:
    """Fetch a URL and return (html, final_url)."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    domain = re.sub(r"^www\.", "", domain)

    if any(blocked in domain for blocked in BLOCKED_DOMAINS):
        raise HTTPException(400, f"Domain {domain} is blocked.")

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=15.0,
        headers={
            "User-Agent": USER_AGENTS[uuid.uuid4().int % len(USER_AGENTS)],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            "Referer": "https://www.google.com/",
        },
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text, str(resp.url)


def _rewrite_links(html: str, base_url: str, proxy_base: str = PUBLIC_URL) -> str:
    """Rewrite all <a href> links to route through our proxy.

    Skips anchors (#), javascript:, mailto:, tel:, data:.
    All other links — internal and external — go through the proxy
    so the user never leaves the proxy browser.
    """
    def _replace_tag(match):
        full_tag = match.group(0)
        def _replace_href(m):
            q = m.group(1)
            href = m.group(2)
            if href.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
                return m.group(0)
            # Don't rewrite links already pointing to our proxy
            if href.startswith(proxy_base):
                return m.group(0)
            absolute = urljoin(base_url, href)
            new_href = f'{proxy_base}/proxy?url={quote(absolute, safe="")}'
            return f'href={q}{new_href}{q}'
        return re.sub('href=(["\'])(.*?)\\1', _replace_href, full_tag)

    return re.sub(r'<a\b[^>]*?>', _replace_tag, html, flags=re.IGNORECASE | re.DOTALL)


# ── Strip endpoint (original) ────────────────────────────────────────────
@app.get("/fetch")
async def fetch_url(url: str = Query(..., description="Target URL to fetch and strip")):
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


# ── Root page ────────────────────────────────────────────────────────────
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
  .nav { display: flex; gap: 8px; margin-bottom: 20px; }
  .nav a {
    flex: 1; text-align: center; text-decoration: none; border-radius: 10px;
    padding: 10px; font-size: 13px; font-weight: 600;
  }
  .nav a.stripper { background: #8AB4F8; color: #0D1117; }
  .nav a.browser { background: #2D2D2D; color: #E8EAED; border: 1px solid #3D3D3D; }
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
  .badge {
    display: inline-block; background: #F28B82; color: #0D1117;
    font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 6px;
    margin-left: 6px; vertical-align: middle;
  }
</style>
</head>
<body>
<div class="card">
  <h1>⚡ StripWall</h1>
  <p class="sub">Dos formas de usar:</p>
  <div class="nav">
    <a href="#" class="stripper" onclick="document.getElementById('fetch-form').style.display='';document.getElementById('browse-form').style.display='none';this.className='stripper';document.querySelector('.nav a.browser').className='browser'">⚡ Stripper</a>
    <a href="#" class="browser" onclick="document.getElementById('browse-form').style.display='';document.getElementById('fetch-form').style.display='none';this.className='stripper';document.querySelector('.nav a.stripper').className='browser'">🌐 Browser</a>
  </div>
  <form id="fetch-form" action="/go" method="get" style="display:block">
    <input type="text" inputmode="url" name="url" placeholder="URL del artículo" required autofocus>
    <button type="submit">Go</button>
  </form>
  <form id="browse-form" action="/proxy" method="get" style="display:none">
    <input type="text" inputmode="url" name="url" placeholder="Navegá cualquier sitio" required>
    <button type="submit">Ir</button>
  </form>
  <div class="footer">
    <a href="/bookmark">Bookmarklet</a> · Modo Browser con ✂ interactivo <span class="badge">NUEVO</span>
  </div>
</div>
</body>
</html>"""


@app.get("/")
async def root():
    return HTMLResponse(content=ROOT_PAGE, status_code=200)


# ── Go redirect: /go?url=... → /fetch?url=... ────────────────────────────
@app.get("/go")
async def go(url: str = Query(...)):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return RedirectResponse(url=f"/fetch?url={url}")


# ── Browse page (landing for proxy browser) ──────────────────────────────
BROWSE_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StripWall — Browser</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #121212; color: #E8EAED; display: flex;
    justify-content: center; align-items: center; min-height: 100vh; padding: 24px;
  }
  .card { background: #1E1E1E; border-radius: 16px; padding: 32px; max-width: 480px; width: 100%; }
  h1 { font-size: 24px; margin-bottom: 4px; color: #8AB4F8; }
  p { color: #9AA0A6; font-size: 13px; margin-bottom: 20px; line-height: 1.5; }
  p strong { color: #E8EAED; }
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
  .steps { margin-top: 20px; }
  .step {
    background: #2D2D2D; border-radius: 10px; padding: 12px 16px;
    margin-bottom: 8px; font-size: 13px; line-height: 1.5;
  }
  .step strong { color: #8AB4F8; }
  .back { display: inline-block; margin-top: 16px; color: #8AB4F8; font-size: 13px; text-decoration: none; }
</style>
</head>
<body>
<div class="card">
  <h1>🌐 StripWall Browser</h1>
  <p>Navegá cualquier sitio. Cuando veas un popup, paywall o elemento molesto, tocá <strong>✂</strong> y eliminá lo que quieras tocándolo.</p>
  <form action="/proxy" method="get">
    <input type="text" inputmode="url" name="url" placeholder="https://ejemplo.com/articulo" required autofocus>
    <button type="submit">Ir</button>
  </form>
  <div class="steps">
    <div class="step"><strong>1.</strong> Ingresá cualquier URL y tocá "Ir"</div>
    <div class="step"><strong>2.</strong> Tocá <strong>✂ Limpiar</strong> (abajo) para activar modo limpieza</div>
    <div class="step"><strong>3.</strong> Tocá los elementos que quieras eliminar — desaparecen al instante</div>
    <div class="step"><strong>4.</strong> Tocá <strong>✔ Hecho</strong> para volver a navegar normal</div>
  </div>
  <a href="/" class="back">← Volver a StripWall</a>
</div>
</body>
</html>"""


@app.get("/browse")
async def browse():
    return HTMLResponse(content=BROWSE_PAGE, status_code=200)


# ── Toolbar HTML + JS that gets injected into proxied pages ──────────────
PROXY_TOOLBAR = """
<div id="sw-toolbar">
  <a href="https://stripwall.amago.fyi/browse" id="sw-home" title="Volver">&#8962;</a>
  <input type="url" id="sw-url" value="__CURRENT_URL__" placeholder="Navegar a...">
  <button id="sw-go">Ir</button>
  <button id="sw-btn">&#9986; Limpiar</button>
</div>
<style>
  #sw-toolbar {
    all: revert;
    position: fixed !important; bottom: 0 !important; left: 0 !important; right: 0 !important;
    z-index: 2147483647 !important;
    background: #1E1E1E !important; padding: 6px 10px !important;
    display: flex !important; gap: 6px !important; align-items: center !important;
    border-top: 1px solid #3D3D3D !important;
    box-shadow: 0 -2px 12px rgba(0,0,0,0.4) !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
    font-size: 13px !important; line-height: normal !important; box-sizing: border-box !important;
  }
  #sw-toolbar * {
    all: revert; box-sizing: border-box !important;
  }
  #sw-toolbar input {
    flex: 1 !important; height: 34px !important;
    background: #0D1117 !important; border: 1px solid #3D3D3D !important;
    border-radius: 8px !important; padding: 0 10px !important;
    color: #E8EAED !important; font-size: 12px !important;
    font-family: inherit !important; outline: none !important; min-width: 0 !important;
  }
  #sw-toolbar input:focus { border-color: #8AB4F8 !important; }
  #sw-toolbar button {
    height: 34px !important; white-space: nowrap !important;
    background: #8AB4F8 !important; color: #0D1117 !important;
    border: none !important; border-radius: 8px !important;
    padding: 0 14px !important; font-size: 12px !important;
    font-weight: 700 !important; cursor: pointer !important;
    font-family: inherit !important;
  }
  #sw-toolbar #sw-go {
    background: #2D2D2D !important; color: #E8EAED !important;
    border: 1px solid #3D3D3D !important;
  }
  #sw-toolbar button.sw-active {
    background: #F28B82 !important; color: #fff !important;
  }
  #sw-toolbar button:hover { opacity: 0.85 !important; }
  #sw-toolbar #sw-home {
    text-decoration: none !important; color: #9AA0A6 !important;
    font-size: 20px !important; line-height: 1 !important;
    padding: 4px !important; cursor: pointer !important;
  }
  #sw-toolbar #sw-home:hover { color: #E8EAED !important; }

  /* Cleanup mode highlight */
  .sw-cleanup-hover {
    outline: 3px solid #F28B82 !important;
    outline-offset: 2px !important;
    cursor: crosshair !important;
  }
  .sw-cleanup-removing {
    transition: all 0.2s ease !important;
    opacity: 0 !important;
    transform: scale(0.95) !important;
  }
  body.sw-cleanup-mode {
    cursor: crosshair !important;
  }
  body.sw-cleanup-mode * {
    cursor: crosshair !important;
  }
</style>
<script>
(function(){
  var toolbar = document.getElementById('sw-toolbar');
  var urlInput = document.getElementById('sw-url');
  var btn = document.getElementById('sw-btn');
  var goBtn = document.getElementById('sw-go');
  var cleanupOn = false;
  var lastRemoved = [];

  function navigate() {
    var u = urlInput.value.trim();
    if (!u) return;
    if (!u.startsWith('http://') && !u.startsWith('https://')) u = 'https://' + u;
    window.location.href = 'https://stripwall.amago.fyi/proxy?url=' + encodeURIComponent(u);
  }

  // URL navigation via Enter key
  urlInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      navigate();
    }
  });

  // URL navigation via Go button
  goBtn.addEventListener('click', function(e) {
    e.preventDefault();
    navigate();
  });

  // Toggle cleanup
  function toggleCleanup() {
    cleanupOn = !cleanupOn;
    btn.textContent = cleanupOn ? '\u2714 Hecho' : '\u2702 Limpiar';
    btn.className = cleanupOn ? 'sw-active' : '';
    document.body.classList.toggle('sw-cleanup-mode', cleanupOn);
    if (!cleanupOn) {
      document.querySelectorAll('.sw-cleanup-hover').forEach(function(el) {
        el.classList.remove('sw-cleanup-hover');
      });
    }
  }
  btn.addEventListener('click', toggleCleanup);

  // Undo last removal
  document.addEventListener('keydown', function(e) {
    if (e.key === 'z' && (e.ctrlKey || e.metaKey) && cleanupOn) {
      var el = lastRemoved.pop();
      if (el && el._swParent) {
        el._swParent.insertBefore(el, el._swNextSibling);
        el.style.transition = '';
        el.style.opacity = '';
        el.style.transform = '';
      }
    }
    if (e.key === 'Escape' && cleanupOn) {
      toggleCleanup();
    }
  });

  // Hover highlight
  document.addEventListener('mouseover', function(e) {
    if (!cleanupOn) return;
    if (e.target.closest('#sw-toolbar')) return;
    document.querySelectorAll('.sw-cleanup-hover').forEach(function(el) {
      el.classList.remove('sw-cleanup-hover');
    });
    if (e.target !== document.body && e.target !== document.documentElement) {
      e.target.classList.add('sw-cleanup-hover');
    }
  }, true);

  // Click to remove
  document.addEventListener('click', function(e) {
    if (!cleanupOn) return;
    if (e.target.closest('#sw-toolbar')) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();

    var el = e.target;
    lastRemoved.push({
      _swParent: el.parentNode,
      _swNextSibling: el.nextSibling
    });
    el.classList.add('sw-cleanup-removing');
    setTimeout(function() {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 200);
  }, true);

  // Touch support for mobile
  document.addEventListener('touchstart', function(e) {
    if (!cleanupOn) return;
    if (e.target.closest('#sw-toolbar')) return;
    e.preventDefault();
  }, {passive: false});

  document.addEventListener('touchend', function(e) {
    if (!cleanupOn) return;
    if (e.target.closest('#sw-toolbar')) return;
    e.preventDefault();

    var el = e.target;
    lastRemoved.push({
      _swParent: el.parentNode,
      _swNextSibling: el.nextSibling
    });
    el.classList.add('sw-cleanup-removing');
    setTimeout(function() {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 200);
  }, {passive: false});

  // Rewrite link clicks to stay in proxy (safety net for dynamic links)
  document.addEventListener('click', function(e) {
    if (cleanupOn) return;
    var a = e.target.closest('a');
    if (!a) return;
    var href = a.getAttribute('href');
    if (!href) return;
    if (href.startsWith('#') || href.startsWith('javascript:') ||
        href.startsWith('mailto:') || href.startsWith('tel:') ||
        href.startsWith('data:')) return;
    if (href.startsWith('https://stripwall.amago.fyi/')) return;
    if (a.target === '_blank') return;
    e.preventDefault();
    var resolved = new URL(href, window.location.href).href;
    window.location.href = 'https://stripwall.amago.fyi/proxy?url=' + encodeURIComponent(resolved);
  }, true);
})();
</script>
"""

# ── Proxy browser endpoint ───────────────────────────────────────────────
@app.get("/proxy")
async def proxy(url: str = Query(..., description="URL to browse through interactive proxy")):
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

    # ── Inject <base> tag for correct relative URL resolution ──
    base_tag = f'<base href="{final_url}">'
    head_close = raw_html.lower().find("</head>")
    if head_close != -1:
        existing_base = re.search(r'<base[^>]*>', raw_html[:head_close], re.IGNORECASE)
        if existing_base:
            raw_html = raw_html[:existing_base.start()] + base_tag + raw_html[existing_base.end():]
        else:
            raw_html = raw_html[:head_close] + base_tag + raw_html[head_close:]
    else:
        raw_html = raw_html.replace("<head>", "<head>" + base_tag, 1)

    # ── Inject toolbar before </body> ──
    toolbar = PROXY_TOOLBAR.replace("__CURRENT_URL__", final_url)
    body_close = raw_html.lower().rfind("</body>")
    if body_close != -1:
        raw_html = raw_html[:body_close] + toolbar + raw_html[body_close:]
    else:
        raw_html += toolbar

    # ── Rewrite links to stay inside the proxy ──
    raw_html = _rewrite_links(raw_html, final_url)

    return HTMLResponse(content=raw_html)


# ── Health check ─────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"pong": True}


# ── Bookmarklet page ─────────────────────────────────────────────────────
BOOKMARKLET_CODE = "javascript:location.href='https://stripwall.amago.fyi/fetch?url='+encodeURIComponent(location.href)"
BOOKMARKLET_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StripWall — Bookmarklet</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #121212; color: #E8EAED; display: flex;
    justify-content: center; align-items: center; min-height: 100vh; padding: 24px;
  }
  .card { background: #1E1E1E; border-radius: 16px; padding: 32px; max-width: 480px; width: 100%; text-align: center; }
  h1 { font-size: 24px; margin-bottom: 8px; color: #8AB4F8; }
  p { color: #B0B0B0; font-size: 14px; line-height: 1.6; margin-bottom: 24px; }
  a.bookmarklet {
    display: inline-block; background: #8AB4F8; color: #0D1117;
    text-decoration: none; font-weight: 700; font-size: 16px;
    padding: 14px 32px; border-radius: 12px; margin-bottom: 24px;
  }
  a.bookmarklet:hover { background: #9DC3FA; }
  .steps { text-align: left; }
  .step {
    background: #2D2D2D; border-radius: 10px; padding: 12px 16px;
    margin-bottom: 10px; font-size: 13px; line-height: 1.5;
  }
  .step strong { color: #8AB4F8; }
  code {
    background: #0D1117; color: #E8EAED; padding: 2px 6px;
    border-radius: 4px; font-size: 12px; word-break: break-all;
  }
  .url-box {
    background: #0D1117; border: 1px solid #3D3D3D; border-radius: 8px;
    padding: 12px; font-size: 11px; word-break: break-all;
    color: #9AA0A6; margin: 16px 0; user-select: all;
  }
</style>
</head>
<body>
<div class="card">
  <h1>⚡ StripWall</h1>
  <p>Un click para leer cualquier articulo sin paywalls, popups ni overlays.</p>
  <a class="bookmarklet" href="javascript:location.href='https://stripwall.amago.fyi/fetch?url='+encodeURIComponent(location.href)">📌 StripWall</a>
  <div class="steps">
    <div class="step"><strong>1.</strong> Arrastra el boton de arriba a tu barra de marcadores en desktop.<br><small>O copia el codigo abajo si estas en mobile.</small></div>
    <div class="step"><strong>2.</strong> Cuando estes en un articulo con paywall, toca el bookmarklet.</div>
    <div class="step"><strong>3.</strong> Listo! El articulo se abre limpio en una pestana.</div>
  </div>
  <div class="url-box">javascript:location.href='https://stripwall.amago.fyi/fetch?url='+encodeURIComponent(location.href)</div>
  <p style="font-size:12px;color:#5F6368">
    Codigo: crea un bookmark y pega eso como URL.<br>
    Funciona en Chrome, Safari, Firefox, Samsung Internet.
  </p>
  <p style="font-size:12px;color:#5F6368;margin-top:12px">
    Queres un navegador interactivo? Proba <a href="/browse" style="color:#8AB4F8">🌐 StripWall Browser</a>
  </p>
</div>
</body>
</html>"""


@app.get("/bookmark", response_class=HTMLResponse)
async def bookmark_page():
    return HTMLResponse(content=BOOKMARKLET_PAGE, status_code=200)
