# StripWall

A **self-hosted paywall/overlay stripper** + **Android client**.

Fetch any article URL through the backend — it strips cookie banners, signup
popups, subscription gates, sticky overlays, and JS paywalls. Returns clean
HTML with layout and images preserved.

No subscription. No API key. You own the whole stack.

---

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Android App │────▶│  Backend     │────▶│  Target URL  │
│  (WebView)   │◀────│  FastAPI     │◀────│              │
└──────────────┘     └──────────────┘     └──────────────┘
                         Port 8150
```

**Backend** — Python/FastAPI. Fetches the URL, strips junk via DOM parsing,
returns clean HTML.

**Android app** — Kotlin + Jetpack Compose. URL input bar + WebView that
loads the cleaned page from your backend.

---

## Quick Start

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8150
```

Test it:

```bash
curl "http://localhost:8150/fetch?url=https://example.com"
```

### 2. Android App

1. Open `android/` in **Android Studio**
2. Edit `BACKEND_HOST` in `app/build.gradle.kts`:
   - Emulator: `http://10.0.2.2:8150`
   - Physical device + same WiFi: `http://192.168.x.x:8150`
   - Public deployment: `https://your-domain.com`
3. Build and run on device/emulator

### 3. Deploy (optional — public server)

```bash
# Behind nginx/caddy with TLS
# Or use Cloudflare Tunnel (recommended):
cloudflared tunnel --url http://localhost:8150
```

---

## What it strips

| Junk | Method |
|---|---|
| Paywall overlays | Class/id patterns (`paywall`, `gate`, `premium`) |
| Cookie / GDPR banners | Class/id patterns (`cookie`, `consent`, `gdpr`) |
| Signup popups | Newsletter modals, registration prompts |
| Sticky elements | Elements with `position: fixed` at high z-index |
| Full-screen modals | Overlay containers, lightboxes |
| Interstitials | Subscription walls, article-limit gates |
| Script tags | All inline/external JS removed |
| Empty wrappers | Cleanup pass removes empty divs/sections |

---

## Configuration

Set `BACKEND_HOST` in `android/app/build.gradle.kts` and rebuild. That's it.

---

## License

MIT
