# MMA Deployment & UX Overhaul — Design Spec

**Goal:** Make the math-modeling-assistant accessible on any device with zero installation, while keeping desktop .exe as a fallback option. Add comprehensive UI animation system.

**Architecture:** Railway cloud deployment (Flask + gunicorn) serves as primary access point. PWA enables mobile "app-like" install. Desktop PyInstaller .exe retained as offline fallback. All devices share one codebase — no platform forks.

**Tech Stack:** Flask, gunicorn, vanilla HTML/CSS/JS, PWA (Service Worker + manifest), PyInstaller, Railway

## Global Constraints

- No new frontend frameworks (React, Vue, Tailwind) — vanilla JS/CSS only
- Backend business logic unchanged — only CORS + WSGI server added
- API Key stored client-side (localStorage), never on server
- One codebase, all platforms
- Dark mode must work on all new UI components
- All existing features preserved — Generator, Paper, Models, Problems, Guide, Roles

---

## Section 1: Cloud Deployment

### Railway Setup

Two new config files at project root:

**`Procfile`**:
```
web: gunicorn app:app -b 0.0.0.0:$PORT -w 2 --timeout 120
```

**`railway.json`**:
- Python 3.10 runtime
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app -b 0.0.0.0:$PORT`

### Backend Changes (`app.py`)

Add CORS middleware after `app = Flask(__name__)`:
- Allow all origins (`*`) — no cookie-based auth, API Key passed in header
- All existing endpoints unchanged

### API Key Flow

- Frontend sends `X-API-Key` header with each request
- Backend reads it, passes to DeepSeek
- Key never persisted on server
- If header missing, backend returns 401 → frontend shows setup modal

---

## Section 2: API Key Setup Modal

### Behavior

- First visit: modal appears automatically
- User enters DeepSeek Key → click "保存" → modal closes
- Key stored in `localStorage('mma-api-key')`
- All subsequent API calls attach `X-API-Key` header
- Settings accessible anytime via gear icon (⚙) in nav footer

### UI

- Centered modal overlay, 400px max-width
- Single text input + "获取 Key" link (→ platform.deepseek.com)
- "保存" button with loading state on verify
- On save: call `/api/check-key` to verify, show success/error toast

### Backend Change

Modify `/api/check-key` to accept `X-API-Key` header instead of reading from config:
- Remove `import config`
- Accept key from request header
- Test with minimal API call to DeepSeek
- Return `{status: "ok"}` or `{status: "error", message: "..."}`

### All Other Endpoints

Modify `src/llm_client.py` to accept optional `api_key` parameter:
- `generate_response(system, user, max_tokens, api_key=None)`
- `generate_stream(system, user, max_tokens, api_key=None)`
- If api_key provided, use it; otherwise fall back to config

All Flask endpoints read `X-API-Key` header and pass to llm_client functions.

---

## Section 3: PWA Enhancement

### Service Worker (`static/sw.js`)

**Cache strategy:**
- Static assets (CSS, JS, manifest): Cache First, pre-cache on install
- API data (`/api/models`, `/api/problems`, `/api/guide`): Network First, fallback to cache
- Generation requests: Network Only (never cache)

**Offline fallback page:**
- When user is offline and requests a non-cached page, show cached offline.html
- Offline page lists available cached content (model library, problem bank, guide)

### Install Prompt

- After 3rd visit (track with `localStorage('mma-visit-count')` increment on each page load), show bottom banner:
  "将此应用添加到主屏幕以获得更好体验"
- iOS: instruction text "点击分享按钮 → 添加到主屏幕"
- Android: uses `beforeinstallprompt` event, show custom banner

### Manifest Update

- Add `display: "standalone"` and `scope: "/"`
- Add 192x192 and 512x512 icons (generate from SVG placeholder)

---

## Section 4: Responsive Mobile Layout

### Breakpoints

- Desktop: > 768px (current layout preserved)
- Tablet: 480px - 768px
- Mobile: < 480px

### Mobile Changes (< 768px)

**Navigation:**
- Top nav bar → fixed bottom Tab Bar
- 5 icons + labels: Generator, Paper, Models, Problems, Guide
- Roles moved into Guide tab as a section
- Theme toggle moved to settings (gear icon)

**Layout:**
- `.card` padding reduced from 24px to 16px
- `.hero h1` font-size smaller
- `.field-row` collapses to single column
- Stats bar becomes 2x2 grid

**Sidebar → Fullscreen Modal:**
- `.result-sidebar` becomes full-width, full-height overlay
- Close button larger (44px touch target)
- Content scrolls independently

**Quick Actions → Horizontal Scroll Chips:**
- `.quick-actions-bar` becomes horizontally scrollable row
- Each button compact, icon-only or icon+short text
- Scroll snap for tactile feel

**Tables → Horizontal Scroll:**
- All markdown tables wrapped in `.table-wrapper` with `overflow-x: auto`

**Paper Preview:**
- `.paper-page` max-width removed, full-width on mobile
- Font size slightly reduced

**TOC Sidebar:**
- Hidden on mobile (< 768px) — replaced by a sticky "目录" dropdown button at top of content

### Tablet (480px - 768px)

- Intermediate sizing
- Nav stays top but compressed
- Sidebar width reduced to 320px

---

## Section 5: Animation System

### L1: CSS Transitions (Global)

Add to `:root`-scoped selectors:

**Tab content switch:**
```css
.tab {
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.2s ease-out, transform 0.2s ease-out;
}
.tab.active {
  opacity: 1;
  transform: translateY(0);
}
```

**Card hover:**
```css
.card, .model-card, .viz-template {
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.card:hover { transform: translateY(-1px); box-shadow: var(--shadow-lg); }
```

**Button press:**
```css
.btn-primary:active, .btn-sm:active {
  transform: scale(0.97);
  transition: transform 0.1s ease;
}
```

### L2: Sidebar & Modal (Web Animations API)

**Sidebar slide-in:**
```javascript
// open: translateX(100%) → translateX(0), 300ms, cubic-bezier(0.22, 1, 0.36, 1)
// backdrop: opacity 0 → 1, 250ms
// close: reverse animation, 200ms
```

**Explain panel:**
```css
.explain-panel {
  animation: slideUp 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

**Modal (API Key setup, shortcuts):**
```css
@keyframes modalIn {
  from { opacity: 0; transform: scale(0.95); }
  to   { opacity: 1; transform: scale(1); }
}
```

### L3: Streaming Generation (JS-driven)

**Stage indicator (already exists, enhance):**
- Pulsing dot: `@keyframes pulse { 0%,100% {opacity:1} 50% {opacity:0.3} }`
- Smooth text transition when stage changes

**Content injection:**
- New paragraphs fade in gradually (CSS animation on `.markdown-body > *`)
- Streaming cursor: blinking block (`@keyframes blink`)

**Skeleton screen (while loading):**
- Gray animated placeholder blocks before first content arrives
- `@keyframes shimmer` gradient sweep

**Completion:**
- Result card gets subtle border glow for 2s
- Paper stats bar slides down

### L4: Micro-interactions

**Toast:**
```css
@keyframes toastIn {
  from { opacity: 0; transform: translateY(-12px); }
  to   { opacity: 1; transform: translateY(0); }
}
```
Auto-dismiss with `toastOut` reverse animation after 3s.

**Copy button feedback:**
- Icon swaps from 📋 to ✓ for 1.5s with scale bounce

**Star/favorite:**
```css
@keyframes starPop {
  0% { transform: scale(1); }
  50% { transform: scale(1.3); }
  100% { transform: scale(1); }
}
```

**Model card hover glow:**
- Border color transitions to accent with subtle box-shadow glow

---

## Section 6: Desktop Build Improvement

### `build.py` (New — replaces win_build.bat + mac_build.sh)

```python
"""One-command build script for MMA desktop app."""
import platform, subprocess, sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def build():
    system = platform.system()
    # Clean + PyInstaller with platform spec
    # Output single-file executable
    # Create ZIP archive
    pass
```

- Auto-detects macOS vs Windows
- Runs appropriate PyInstaller spec
- Outputs single file to `dist/`
- Shows build summary with file size

### Keep Existing

- `win_build.spec` — unchanged
- `mac_build.spec` — unchanged
- `launcher.py` / `launcher_win.pyw` — unchanged
- `requirements.txt` — add `gunicorn`, `gevent`

---

## Section 7: File Changes Summary

| File | Action | Lines |
|------|--------|-------|
| `Procfile` | **New** | 1 |
| `railway.json` | **New** | 8 |
| `build.py` | **New** | ~60 |
| `app.py` | Modify | +5 (CORS + check-key header) |
| `src/llm_client.py` | Modify | +10 (api_key param) |
| `requirements.txt` | Modify | +2 (gunicorn, gevent) |
| `templates/index.html` | Modify | +40 (setup modal, gear icon, PWA install banner) |
| `static/style.css` | Modify | +700 (responsive + animations) |
| `static/script.js` | Modify | +200 (setup modal, PWA install, animation triggers) |
| `static/sw.js` | Modify | +30 (enhanced caching) |
| `static/manifest.json` | Modify | +5 (display, scope) |
| `static/offline.html` | **New** | ~30 |

**Total: ~1100 lines across 12 files, 3 new, 9 modified.**

---

## Section 8: What Does NOT Change

- All 18 API endpoints (except `/api/check-key` header reading)
- All prompt templates in `src/prompts.py`
- Data files: `models_data.py`, `problems_data.py`, `guide_data.py`, `scholar.py`
- All existing JS functions (wrapped with animation triggers, not rewritten)
- PyInstaller spec files
- README (updated URLs only)
