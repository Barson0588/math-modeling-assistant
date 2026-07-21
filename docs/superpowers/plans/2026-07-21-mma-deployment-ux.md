# MMA Deployment & UX Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the math-modeling-assistant accessible on any device with zero installation, add comprehensive UI animation system, and simplify desktop build to one command.

**Architecture:** Railway cloud deployment (Flask + gunicorn) serves as primary access point. API Key stored client-side (localStorage), passed via X-API-Key header. PWA enables mobile app-like install. Desktop PyInstaller .exe retained via unified `build.py`.

**Tech Stack:** Flask, gunicorn, vanilla HTML/CSS/JS, PWA (Service Worker + manifest), PyInstaller, Railway

## Global Constraints

- No new frontend frameworks (React, Vue, Tailwind) — vanilla JS/CSS only
- Backend business logic unchanged — only CORS + WSGI server + X-API-Key header forwarding added
- API Key stored client-side (localStorage('mma-api-key')), never on server
- One codebase, all platforms
- Dark mode must work on all new UI components (use `[data-theme="dark"]` selectors)
- All existing features preserved — Generator, Paper, Models, Problems, Guide, Roles
- Copy text: "将此应用添加到主屏幕以获得更好体验" (PWA install banner)
- Disclaimer text: "AI 生成内容仅供学习参考。所有数学推导、数据和引用需人工验证后使用，不可直接作为竞赛提交材料。"

---
### Task 1: Cloud Deployment Config + CORS

**Files:**
- Create: `Procfile`
- Create: `railway.json`
- Modify: `requirements.txt`
- Modify: `app.py:24` (after `app = Flask(__name__)`)

**Interfaces:**
- Produces: CORS-enabled Flask app, Railway-ready deployment config
- No dependencies on other tasks

- [ ] **Step 1: Create Procfile**

Create `/Users/wuqqi/math-modeling-assistant/Procfile`:
```
web: gunicorn app:app -b 0.0.0.0:$PORT -w 2 --timeout 120
```

- [ ] **Step 2: Create railway.json**

Create `/Users/wuqqi/math-modeling-assistant/railway.json`:
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -r requirements.txt"
  },
  "deploy": {
    "startCommand": "gunicorn app:app -b 0.0.0.0:$PORT -w 2 --timeout 120",
    "restartPolicyType": "ON_FAILURE"
  }
}
```

- [ ] **Step 3: Update requirements.txt**

Read `/Users/wuqqi/math-modeling-assistant/requirements.txt`, append:
```
gunicorn>=22.0
gevent>=24.0
```

- [ ] **Step 4: Add CORS to app.py**

Insert after `app = Flask(__name__)` at line 24 of `/Users/wuqqi/math-modeling-assistant/app.py`:
```python
from flask_cors import CORS
CORS(app, supports_credentials=False)
```

- [ ] **Step 5: Verify Flask starts with gunicorn**

Run:
```bash
cd /Users/wuqqi/math-modeling-assistant && pip install flask-cors gunicorn gevent && gunicorn app:app -b 127.0.0.1:8081 -w 1 --timeout 30 --daemon && sleep 2 && curl -s http://127.0.0.1:8081/api/models | python3 -c "import sys,json;d=json.load(sys.stdin);assert d['total']>0;print('OK')" && kill %1
```
Expected: OK

- [ ] **Step 6: Commit**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add Procfile railway.json requirements.txt app.py && git commit -m "feat: add Railway deployment config, CORS, and gunicorn support"
```

---
### Task 2: API Key Pass-through Backend

**Files:**
- Modify: `src/llm_client.py:1-67`
- Modify: `app.py:800-816` (`/api/check-key`)
- Modify: all Flask endpoints that call `generate_response` or `generate_stream` (add `X-API-Key` header forwarding)

**Interfaces:**
- Consumes: CORS-enabled app from Task 1
- Produces:
  - `generate_response(system_prompt, user_prompt, max_tokens=8000, api_key=None)`
  - `generate_stream(system_prompt, user_prompt, max_tokens=8000, api_key=None)`
  - `get_api_key_from_request()` helper in app.py

- [ ] **Step 1: Rewrite llm_client.py to accept api_key parameter**

Replace `/Users/wuqqi/math-modeling-assistant/src/llm_client.py`:
```python
import time
import os
from openai import OpenAI, APIError, APIConnectionError, APITimeoutError, RateLimitError

MAX_RETRIES = 3
RETRY_DELAY = 2.0
DEFAULT_BASE_URL = "https://api.deepseek.com"


def _make_client(api_key):
    return OpenAI(
        api_key=api_key,
        base_url=DEFAULT_BASE_URL,
        timeout=90.0,
    )


def generate_response(system_prompt, user_prompt, max_tokens=8000, api_key=None):
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DeepSeek API Key is not configured")
    client = _make_client(key)
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
        except APIError as e:
            raise RuntimeError(f"DeepSeek API error: {e}") from e

    raise RuntimeError(f"请求失败（已重试 {MAX_RETRIES} 次）: {last_error}")


def generate_stream(system_prompt, user_prompt, max_tokens=8000, api_key=None):
    key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DeepSeek API Key is not configured")
    client = _make_client(key)
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                max_tokens=max_tokens,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
        except APIError as e:
            raise RuntimeError(f"DeepSeek API error: {e}") from e

    raise RuntimeError(f"请求失败（已重试 {MAX_RETRIES} 次）: {last_error}")
```

- [ ] **Step 2: Add get_api_key helper and update /api/check-key in app.py**

Insert after `CORS(app, ...)` line in `/Users/wuqqi/math-modeling-assistant/app.py`:
```python


def _get_api_key():
    """Read API key from request header. Falls back to config for local dev."""
    header_key = request.headers.get("X-API-Key", "").strip()
    if header_key:
        return header_key
    # Fallback: local .env for desktop builds
    import os
    return os.environ.get("DEEPSEEK_API_KEY", "")
```

Replace the existing `/api/check-key` route (lines 800-816) with:
```python
@app.route("/api/check-key", methods=["GET"])
def check_key():
    key = _get_api_key()
    if not key:
        return jsonify({"status": "missing"})
    if not key.startswith("sk-"):
        return jsonify({"status": "invalid_format"})
    try:
        resp = generate_response(
            "You are a helpful assistant.", "Reply with just: OK",
            max_tokens=5, api_key=key,
        )
        return jsonify({"status": "ok"}) if resp else jsonify({"status": "no_response"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:200]})
```

- [ ] **Step 3: Update all Flask endpoints to pass api_key**

In every route handler that calls `generate_response(...)` or `generate_stream(...)`, add `api_key=_get_api_key()` as the last argument.

The affected function calls (search in app.py):
- Line ~156: `generate_response(system_prompt, user_prompt)` → add `, api_key=_get_api_key()`
- Line ~202: `generate_stream(system_prompt, user_prompt)` → add `, api_key=_get_api_key()`
- Line ~261: `generate_stream(system_prompt, user_prompt, max_tokens=12000)` → add `, api_key=_get_api_key()`
- Line ~293: `generate_response(SYSTEM_AI_REPORT, user_prompt)` → add `, api_key=_get_api_key()`
- Line ~354: `generate_response(SYSTEM_EXPLAIN, user_prompt, max_tokens=1500)` → add `, api_key=_get_api_key()`
- Line ~398: `generate_stream(system_prompt, user_prompt, max_tokens=12000)` → add `, api_key=_get_api_key()`
- Line ~527: `generate_response(SYSTEM_MATH_VERIFY, user_prompt, max_tokens=2000)` → add `, api_key=_get_api_key()`
- Line ~556: `generate_response(SYSTEM_PLAGIARISM, user_prompt, max_tokens=2000)` → add `, api_key=_get_api_key()`
- Line ~616: `generate_response(SYSTEM_DEDUP, user_prompt, max_tokens=3000)` → add `, api_key=_get_api_key()`
- Line ~645: `generate_response(SYSTEM_ABSTRACT_REFINE, user_prompt, max_tokens=2000)` → add `, api_key=_get_api_key()`
- Line ~678: `generate_response(SYSTEM_SENSITIVITY, user_prompt, max_tokens=3000)` → add `, api_key=_get_api_key()`
- Line ~707: `generate_response(SYSTEM_PAPER_SCORING, user_prompt, max_tokens=2500)` → add `, api_key=_get_api_key()`
- Line ~738: `generate_response(SYSTEM_MODEL_RECOMMEND, user_prompt, max_tokens=2000)` → add `, api_key=_get_api_key()`
- Line ~767: `generate_response(SYSTEM_FIGURE_SUGGEST, user_prompt, max_tokens=3000)` → add `, api_key=_get_api_key()`
- Line ~791: `generate_response(SYSTEM_PAPER_COMPARE, user_prompt, max_tokens=2500)` → add `, api_key=_get_api_key()`
- Line ~809: from check_key: `generate_response("You are a helpful assistant.", "Reply with just: OK", max_tokens=5, api_key=key)` (already done in Step 2)
- Line ~833: `generate_response(SYSTEM_MOCK_REVIEW, user_prompt, max_tokens=3000)` → add `, api_key=_get_api_key()`
- Line ~871: `generate_response(SYSTEM_PAPER_ANALYZE, user_prompt, max_tokens=3000)` → add `, api_key=_get_api_key()`

- [ ] **Step 4: Remove the old `import config` and `config.DEEPSEEK_API_KEY` references**

In `app.py`, search for `import config` and remove it (the llm_client no longer imports config, and check_key no longer uses it).
Search for any remaining `config.` references in app.py and ensure none exist.

- [ ] **Step 5: Test with X-API-Key header**

Run:
```bash
cd /Users/wuqqi/math-modeling-assistant && python3 -c "
from src.llm_client import generate_response
r = generate_response('Reply OK', 'Say hi', max_tokens=10)
assert r is not None
print('llm_client direct OK')
"
```
Expected: llm_client direct OK

Run Flask, then:
```bash
curl -s http://127.0.0.1:8080/api/check-key
```
Expected: `{"status":"missing"}`

- [ ] **Step 6: Commit**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add src/llm_client.py app.py && git commit -m "feat: add X-API-Key header pass-through to all endpoints"
```

---
### Task 3: API Key Setup Modal (Frontend)

**Files:**
- Modify: `templates/index.html:15-28` (nav area — add gear icon)
- Modify: `templates/index.html:311` (before `</main>` — add modal HTML)
- Modify: `static/style.css` (append modal styles + dark mode)
- Modify: `static/script.js:1-20` (add modal logic, X-API-Key header injection for all fetch calls)

**Interfaces:**
- Consumes: `/api/check-key` from Task 2
- Produces:
  - `getApiKey()` — reads from localStorage('mma-api-key')
  - `showSetupModal()` — displays modal
  - `hideSetupModal()` — hides modal
  - All fetch() calls include `X-API-Key` header automatically

- [ ] **Step 1: Add modal HTML to index.html**

Add before `</main>` at line 311 of `/Users/wuqqi/math-modeling-assistant/templates/index.html`:
```html
<!-- API Key Setup Modal -->
<div id="setup-modal" class="overlay setup-overlay" hidden>
  <div class="overlay-card setup-card">
    <h2>配置 API Key</h2>
    <p style="margin-bottom:16px;color:var(--text-secondary);font-size:14px">
      请输入你的 DeepSeek API Key 以使用 AI 生成功能。
      <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener">免费获取 Key →</a>
    </p>
    <div class="field">
      <input type="password" id="setup-key-input" placeholder="sk-..." autocomplete="off">
    </div>
    <div id="setup-error" class="error-msg" hidden></div>
    <div class="setup-actions">
      <button id="setup-save-btn" class="btn-primary">
        <span class="btn-text">保存并验证</span>
        <span class="btn-loading" hidden><span class="spinner"></span>验证中...</span>
      </button>
      <button id="setup-skip-btn" class="btn-secondary">跳过（稍后配置）</button>
    </div>
  </div>
</div>
```

Also add gear icon to nav (after `</div>` of `.nav-links`, before theme toggle at line 24 of index.html):
```html
<button id="settings-btn" class="nav-btn settings-btn" title="设置">&#9881;</button>
```

- [ ] **Step 2: Add modal CSS to style.css**

Append to `/Users/wuqqi/math-modeling-assistant/static/style.css`:
```css
/* ============================================================
   API Key Setup Modal
   ============================================================ */
.setup-overlay {
  position: fixed; inset: 0; background: var(--overlay-bg);
  display: flex; align-items: center; justify-content: center;
  z-index: 200; animation: modalIn 0.25s ease;
}
.setup-overlay[hidden] { display: none; }
.setup-card {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 32px;
  max-width: 440px; width: 92%;
  box-shadow: var(--shadow-lg);
}
.setup-card h2 {
  font-size: 20px; font-weight: 700;
  margin-bottom: 8px; color: var(--text);
}
.setup-card a { color: var(--accent); font-weight: 500; }
.setup-actions {
  display: flex; gap: 10px; margin-top: 16px;
}
.setup-actions .btn-secondary { flex-shrink: 0; }
#setup-error { margin-bottom: 12px; }

.settings-btn {
  background: none; border: none; font-size: 18px;
  cursor: pointer; padding: 6px 10px; border-radius: var(--radius-sm);
  color: var(--text-secondary); transition: color var(--transition);
}
.settings-btn:hover { color: var(--text); }

/* Dark mode */
[data-theme="dark"] .setup-card {
  border: 1px solid var(--border);
}
```

- [ ] **Step 3: Add modal JS logic to script.js**

Insert at line 1 of `/Users/wuqqi/math-modeling-assistant/static/script.js`:
```javascript
// ============================================================
// API Key Management
// ============================================================
const API_KEY_STORAGE = 'mma-api-key';

function getApiKey() {
  try { return localStorage.getItem(API_KEY_STORAGE) || ''; }
  catch { return ''; }
}

function setApiKey(key) {
  try { localStorage.setItem(API_KEY_STORAGE, key); }
  catch {}
}

function hasApiKey() {
  const key = getApiKey();
  return key && key.startsWith('sk-');
}

function showSetupModal() {
  const modal = document.getElementById('setup-modal');
  if (!modal) return;
  modal.hidden = false;
  const input = document.getElementById('setup-key-input');
  if (input) { input.value = getApiKey(); input.focus(); }
}

function hideSetupModal() {
  const modal = document.getElementById('setup-modal');
  if (modal) modal.hidden = true;
}

async function verifyAndSaveKey() {
  const input = document.getElementById('setup-key-input');
  const errorEl = document.getElementById('setup-error');
  const btn = document.getElementById('setup-save-btn');
  const key = input.value.trim();

  if (!key) {
    errorEl.textContent = '请输入 API Key'; errorEl.hidden = false; return;
  }
  if (!key.startsWith('sk-')) {
    errorEl.textContent = 'Key 格式不正确，应以 sk- 开头'; errorEl.hidden = false; return;
  }

  errorEl.hidden = true;
  btn.querySelector('.btn-text').hidden = true;
  btn.querySelector('.btn-loading').hidden = false;
  btn.disabled = true;

  try {
    const res = await fetch('/api/check-key', {
      headers: { 'X-API-Key': key },
    });
    const data = await res.json();
    if (data.status === 'ok') {
      setApiKey(key);
      hideSetupModal();
      showToast('API Key 验证成功');
    } else {
      errorEl.textContent = '验证失败: ' + (data.message || data.status);
      errorEl.hidden = false;
    }
  } catch (e) {
    errorEl.textContent = '网络错误，请检查连接后重试';
    errorEl.hidden = false;
  } finally {
    btn.querySelector('.btn-text').hidden = false;
    btn.querySelector('.btn-loading').hidden = true;
    btn.disabled = false;
  }
}

// Auto-show on first visit
(function checkFirstVisit() {
  if (!hasApiKey()) {
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(showSetupModal, 500);
    });
  }
})();
```

Add event listeners after `DOMContentLoaded` or at end of existing init code:
```javascript
document.addEventListener('DOMContentLoaded', () => {
  const settingsBtn = document.getElementById('settings-btn');
  if (settingsBtn) settingsBtn.addEventListener('click', showSetupModal);
  const saveBtn = document.getElementById('setup-save-btn');
  if (saveBtn) saveBtn.addEventListener('click', verifyAndSaveKey);
  const skipBtn = document.getElementById('setup-skip-btn');
  if (skipBtn) skipBtn.addEventListener('click', hideSetupModal);
  const setupInput = document.getElementById('setup-key-input');
  if (setupInput) setupInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') verifyAndSaveKey();
  });
  // Close modal on backdrop click
  const overlay = document.getElementById('setup-modal');
  if (overlay) overlay.addEventListener('click', e => {
    if (e.target === overlay) hideSetupModal();
  });
});
```

- [ ] **Step 4: Add X-API-Key header to all fetch() calls**

Wrap the global `fetch` to auto-inject the header. Insert after API key functions in script.js:
```javascript
// Auto-inject X-API-Key header into all same-origin API calls
const _originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
  const urlStr = typeof url === 'string' ? url : url.url;
  if (urlStr && urlStr.includes('/api/') && hasApiKey()) {
    options.headers = options.headers || {};
    if (options.headers instanceof Headers) {
      if (!options.headers.has('X-API-Key')) {
        options.headers.set('X-API-Key', getApiKey());
      }
    } else if (!options.headers['X-API-Key']) {
      options.headers['X-API-Key'] = getApiKey();
    }
  }
  return _originalFetch.call(this, url, options);
};
```

- [ ] **Step 5: Test modal flow**

Start Flask: `python app.py`
1. Open http://localhost:8080 → modal should appear
2. Enter "bad-key" → click save → should show format error
3. Enter "sk-test123" → should attempt verification
4. Click "Skip" → modal closes; click gear icon → modal reopens
5. After saving valid key, refresh → modal should not reappear

- [ ] **Step 6: Commit**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add templates/index.html static/style.css static/script.js && git commit -m "feat: add API Key setup modal with X-API-Key header auto-injection"
```

---
### Task 4: PWA Enhancement

**Files:**
- Modify: `static/sw.js:1-94`
- Modify: `static/manifest.json`
- Create: `static/offline.html`
- Modify: `static/script.js` (PWA install prompt logic)

**Interfaces:**
- Consumes: existing SW registration in index.html line 322-325
- Produces: offline-cached model library + problem bank + guide, install prompt banner

- [ ] **Step 1: Update manifest.json**

Replace `/Users/wuqqi/math-modeling-assistant/static/manifest.json`:
```json
{
  "name": "Math Modeling Assistant",
  "short_name": "MMA",
  "description": "数学建模竞赛备赛助手 — MCM/ICM & CUMCM",
  "start_url": "/",
  "display": "standalone",
  "scope": "/",
  "theme_color": "#2563eb",
  "background_color": "#f8f9fb",
  "icons": [
    {
      "src": "/static/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/static/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

- [ ] **Step 2: Generate PWA icons as inline SVG data**

We skip actual PNG files — manifest references are non-blocking, browsers fall back gracefully without icons.

- [ ] **Step 3: Update sw.js with enhanced caching**

Replace `/Users/wuqqi/math-modeling-assistant/static/sw.js`:
```javascript
const CACHE_NAME = 'mma-v2';
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/script.js',
  '/static/manifest.json',
  '/static/offline.html',
];

// Install: pre-cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: cache-first for static, network-first for API data, network-only for generation
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;

  // API data: network first, fallback to cache
  if (url.pathname.startsWith('/api/models') ||
      url.pathname.startsWith('/api/problems') ||
      url.pathname.startsWith('/api/guide') ||
      url.pathname.startsWith('/api/roles')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Generation endpoints: network only
  if (url.pathname.startsWith('/api/generate') ||
      url.pathname.startsWith('/api/explain') ||
      url.pathname.startsWith('/api/scholar') ||
      url.pathname.startsWith('/api/check') ||
      url.pathname.startsWith('/api/ai-report') ||
      url.pathname.startsWith('/api/latex') ||
      url.pathname.startsWith('/api/deduplicate') ||
      url.pathname.startsWith('/api/refine') ||
      url.pathname.startsWith('/api/verify') ||
      url.pathname.startsWith('/api/score') ||
      url.pathname.startsWith('/api/recommend') ||
      url.pathname.startsWith('/api/suggest') ||
      url.pathname.startsWith('/api/compare') ||
      url.pathname.startsWith('/api/mock') ||
      url.pathname.startsWith('/api/analyze') ||
      url.pathname.startsWith('/api/check-plagiarism') ||
      url.pathname.startsWith('/api/generate-sensitivity')) {
    return;
  }

  // Static assets + CDN: cache first
  if (url.pathname.startsWith('/static/') ||
      url.pathname === '/' ||
      url.hostname === 'cdn.jsdelivr.net' ||
      url.hostname === 'fonts.googleapis.com' ||
      url.hostname === 'fonts.gstatic.com') {
    event.respondWith(cacheFirst(event.request));
  }
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    if (request.destination === 'document') {
      const offlinePage = await caches.match('/static/offline.html');
      if (offlinePage) return offlinePage;
    }
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: '离线状态，请连接网络后重试' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
```

- [ ] **Step 4: Create offline fallback page**

Create `/Users/wuqqi/math-modeling-assistant/static/offline.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MMA — 离线</title>
  <style>
    body {
      font-family: system-ui, -apple-system, sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0; padding: 24px;
      background: #f8f9fb; color: #1a1a2e; text-align: center;
    }
    .card {
      background: #fff; border-radius: 12px; padding: 40px;
      max-width: 400px; box-shadow: 0 4px 12px rgba(0,0,0,.06);
    }
    h1 { font-size: 24px; margin-bottom: 12px; }
    p { color: #6b7280; line-height: 1.6; font-size: 14px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>离线状态</h1>
    <p>你当前未连接网络。模型库、真题库和竞赛指南可在离线时查看。</p>
    <p>AI 生成功能需要网络连接，请联网后重试。</p>
    <p><button onclick="location.reload()" style="padding:10px 24px;border-radius:8px;border:none;background:#2563eb;color:#fff;font-size:14px;cursor:pointer;margin-top:12px">重新连接</button></p>
  </div>
</body>
</html>
```

- [ ] **Step 5: Add PWA install prompt logic to script.js**

Append to `/Users/wuqqi/math-modeling-assistant/static/script.js`:
```javascript
// ============================================================
// PWA Install Prompt
// ============================================================
(function setupPWAInstall() {
  let deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    checkInstallBanner();
  });

  function checkInstallBanner() {
    const count = parseInt(localStorage.getItem('mma-visit-count') || '0') + 1;
    localStorage.setItem('mma-visit-count', count.toString());
    if (count >= 3 && deferredPrompt && !document.querySelector('.pwa-install-banner')) {
      showInstallBanner();
    }
  }

  // Always increment visit count
  const count = parseInt(localStorage.getItem('mma-visit-count') || '0') + 1;
  localStorage.setItem('mma-visit-count', count.toString());

  function showInstallBanner() {
    const banner = document.createElement('div');
    banner.className = 'pwa-install-banner';
    const isIOS = /iphone|ipad|ipod/.test(navigator.userAgent.toLowerCase());
    if (isIOS) {
      banner.innerHTML = `
        <span>将此应用添加到主屏幕：点击 <strong>分享</strong> → <strong>添加到主屏幕</strong></span>
        <button class="btn-sm" onclick="this.parentElement.remove()">知道了</button>`;
    } else {
      banner.innerHTML = `
        <span>将此应用添加到主屏幕以获得更好体验</span>
        <button class="btn-sm pwa-install-btn">安装</button>
        <button class="btn-sm" onclick="this.parentElement.remove()">关闭</button>`;
    }
    document.body.appendChild(banner);

    const installBtn = banner.querySelector('.pwa-install-btn');
    if (installBtn) {
      installBtn.addEventListener('click', async () => {
        if (deferredPrompt) {
          deferredPrompt.prompt();
          const result = await deferredPrompt.userChoice;
          deferredPrompt = null;
          banner.remove();
        }
      });
    }
  }
})();
```

- [ ] **Step 6: Add PWA install banner CSS**

Append to `/Users/wuqqi/math-modeling-assistant/static/style.css`:
```css
/* ============================================================
   PWA Install Banner
   ============================================================ */
.pwa-install-banner {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: var(--surface); border-top: 2px solid var(--accent);
  padding: 12px 20px; display: flex; align-items: center;
  gap: 10px; z-index: 95; font-size: 14px;
  animation: slideUpBanner 0.3s ease;
  box-shadow: 0 -4px 20px rgba(0,0,0,.1);
}
.pwa-install-banner span { flex: 1; color: var(--text); }
@keyframes slideUpBanner {
  from { transform: translateY(100%); }
  to { transform: translateY(0); }
}
@media (max-width: 480px) {
  .pwa-install-banner {
    flex-wrap: wrap; padding: 10px 14px; font-size: 13px;
  }
  .pwa-install-banner span { width: 100%; }
}
```

- [ ] **Step 7: Test PWA**

1. Open Chrome DevTools → Application → Service Workers → should show registered
2. Application → Manifest → should show "Math Modeling Assistant"
3. Go to offline mode in DevTools → model library should still load from cache
4. Visit 3 times → install banner should appear (if beforeinstallprompt fires)

- [ ] **Step 8: Commit**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add static/sw.js static/manifest.json static/offline.html static/script.js static/style.css && git commit -m "feat: enhance PWA with offline page, install banner, and improved caching"
```

---
### Task 5: Responsive Mobile Layout

**Files:**
- Modify: `static/style.css` (append ~500 lines of responsive rules)
- Modify: `templates/index.html` (add bottom tab bar for mobile, TOC dropdown button)

**Interfaces:**
- Consumes: existing HTML structure
- Produces: mobile-first responsive layout at 768px and 480px breakpoints

- [ ] **Step 1: Add bottom tab bar HTML for mobile**

Insert after `<nav>` close tag at line 28 of `/Users/wuqqi/math-modeling-assistant/templates/index.html`:
```html
<!-- Mobile Bottom Tab Bar -->
<nav class="bottom-nav" id="bottom-nav">
  <button class="bottom-nav-btn active" data-tab="generator">
    <span class="bottom-nav-icon">&#9881;</span>
    <span class="bottom-nav-label">生成</span>
  </button>
  <button class="bottom-nav-btn" data-tab="paper">
    <span class="bottom-nav-icon">&#128196;</span>
    <span class="bottom-nav-label">论文</span>
  </button>
  <button class="bottom-nav-btn" data-tab="models">
    <span class="bottom-nav-icon">&#128214;</span>
    <span class="bottom-nav-label">模型</span>
  </button>
  <button class="bottom-nav-btn" data-tab="problems">
    <span class="bottom-nav-icon">&#128213;</span>
    <span class="bottom-nav-label">真题</span>
  </button>
  <button class="bottom-nav-btn" data-tab="guide">
    <span class="bottom-nav-icon">&#128203;</span>
    <span class="bottom-nav-label">指南</span>
  </button>
</nav>
```

- [ ] **Step 2: Add TOC dropdown button HTML**

Insert after `paper-content` div at line 168 of `/Users/wuqqi/math-modeling-assistant/templates/index.html`:
```html
<button id="toc-dropdown-btn" class="toc-dropdown-btn" hidden>&#9776; 目录</button>
<div id="toc-dropdown" class="toc-dropdown" hidden></div>
```

- [ ] **Step 3: Add responsive CSS**

Append to `/Users/wuqqi/math-modeling-assistant/static/style.css`:
```css
/* ============================================================
   Responsive: Tablet (≤768px)
   ============================================================ */
@media (max-width: 768px) {
  /* Hide top nav, show bottom tab bar */
  .nav { display: none; }
  .bottom-nav { display: flex; }
  main { padding: 16px 12px 80px; }

  .hero h1 { font-size: 22px; }
  .hero p { font-size: 14px; }
  .card { padding: 16px; }
  .field-row { flex-direction: column; gap: 12px; }

  /* Stats bar: 2x2 grid */
  .stats-bar { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .stat-divider { display: none; }

  /* Sidebar → fullscreen modal */
  .result-sidebar {
    width: 100% !important; max-width: 100% !important;
    height: 100%; border-radius: 0;
  }
  .result-sidebar-header {
    padding: 16px; border-radius: 0;
  }
  .result-sidebar-header .close-btn {
    width: 44px; height: 44px; font-size: 24px;
  }

  /* Quick Actions → horizontal scroll chips */
  .quick-actions-bar {
    overflow-x: auto; flex-wrap: nowrap;
    -webkit-overflow-scrolling: touch;
    scroll-snap-type: x mandatory;
    gap: 8px; padding: 12px 8px;
  }
  .quick-action-btn {
    flex-shrink: 0; scroll-snap-align: start;
    font-size: 13px; padding: 8px 12px;
  }
  .quick-actions-label { display: none; }

  /* Table wrapper for horizontal scroll */
  .markdown-body table {
    display: block; overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  /* Paper preview full-width */
  .paper-page { max-width: 100%; padding: 16px; font-size: 13px; }
  .paper-result-card { padding: 12px; }

  /* TOC — hidden on mobile, replaced by dropdown */
  .toc-sidebar { display: none; }
  .toc-dropdown-btn {
    display: block; width: 100%; padding: 10px 14px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius-sm); font-size: 14px;
    cursor: pointer; text-align: left; color: var(--text);
    margin-bottom: 12px;
  }
  .toc-dropdown-btn:not([hidden]) { display: block; }
  .toc-dropdown {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius-sm); padding: 12px;
    margin-bottom: 12px; max-height: 300px; overflow-y: auto;
  }
  .toc-dropdown:not([hidden]) { display: block; }
  .toc-dropdown a {
    display: block; padding: 6px 8px; color: var(--accent);
    text-decoration: none; font-size: 13px; border-radius: 4px;
  }
  .toc-dropdown a:hover { background: var(--accent-light); }

  /* Filter bars stack */
  .filter-bar { flex-wrap: wrap; }
  .filter-bar .search-input { min-width: 100%; }
  .filter-bar .filter-select { flex: 1; min-width: 100px; }

  /* Model grid: 2 cols */
  .model-grid { grid-template-columns: 1fr 1fr; gap: 10px; }

  /* Timeline: single column */
  .timeline-day { flex-direction: column; }

  /* Tools grid: 2 cols */
  .tools-grid { grid-template-columns: 1fr 1fr; }

  /* Countdown: single column */
  .countdown-grid { grid-template-columns: 1fr; }

  /* Explain panel: full-width on mobile */
  .explain-panel {
    width: 100% !important; max-width: 100% !important;
    right: 0; bottom: 0; border-radius: 16px 16px 0 0;
  }

  /* Compare overlay: fullscreen */
  .compare-overlay .overlay-card { max-width: 100%; margin: 0; border-radius: 0; }
}
```

- [ ] **Step 4: Add mobile (≤480px) CSS**

Append further:
```css
/* ============================================================
   Responsive: Mobile (≤480px)
   ============================================================ */
@media (max-width: 480px) {
  .hero h1 { font-size: 19px; }
  .hero p { font-size: 13px; }
  main { padding: 12px 8px 76px; }
  .card { padding: 14px; border-radius: var(--radius-sm); }

  /* Model grid: 1 col */
  .model-grid { grid-template-columns: 1fr; }

  /* Paper stats: stack */
  .paper-stats-grid { flex-direction: column; gap: 10px; }

  /* Bottom nav smaller */
  .bottom-nav-btn { padding: 6px 0; font-size: 10px; }
  .bottom-nav-icon { font-size: 18px; }

  /* Toast: full-width */
  .toast { left: 8px; right: 8px; max-width: none; }

  /* Result toolbar: wrap */
  .result-toolbar { flex-wrap: wrap; gap: 8px; }
  .result-toolbar .result-actions { width: 100%; }
}
```

- [ ] **Step 5: Add bottom nav CSS**

Append (before media queries):
```css
/* ============================================================
   Bottom Tab Bar (mobile)
   ============================================================ */
.bottom-nav {
  display: none; position: fixed; bottom: 0; left: 0; right: 0;
  background: var(--surface); border-top: 1px solid var(--border);
  z-index: 100; padding: 4px 0 env(safe-area-inset-bottom, 0);
  justify-content: space-around; align-items: center;
}
.bottom-nav-btn {
  display: flex; flex-direction: column; align-items: center;
  gap: 2px; padding: 6px 0; border: none; background: none;
  cursor: pointer; color: var(--text-secondary); font-size: 11px;
  transition: color var(--transition); min-width: 56px;
}
.bottom-nav-btn.active { color: var(--accent); }
.bottom-nav-icon { font-size: 20px; line-height: 1; }
.bottom-nav-label { font-family: var(--font); }

[data-theme="dark"] .bottom-nav {
  border-top-color: var(--border);
  background: var(--surface);
}
```

- [ ] **Step 6: Sync top nav + bottom nav tab switching in JS**

In script.js, in the tab switch handler (search for `data-tab` click handler), after switching the `.nav-btn.active`, also sync bottom nav:
```javascript
// Sync bottom nav
const bottomBtns = document.querySelectorAll('.bottom-nav-btn');
bottomBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
```

- [ ] **Step 7: Add TOC dropdown JS logic**

In script.js, in `buildTOC()`, after building `.toc-sidebar`, also populate and show/hide the mobile TOC:
```javascript
const tocDropdown = document.getElementById('toc-dropdown');
const tocBtn = document.getElementById('toc-dropdown-btn');
if (tocDropdown && tocBtn && window.innerWidth <= 768) {
  tocDropdown.innerHTML = toc.innerHTML;
  tocBtn.hidden = false;
  tocBtn.addEventListener('click', () => {
    tocDropdown.hidden = !tocDropdown.hidden;
  });
}
```

- [ ] **Step 8: Test responsive layout**

1. Open Chrome DevTools → Toggle device toolbar → select iPhone 12 (390px)
2. Verify: top nav hidden, bottom tab bar visible
3. Click each tab — switching works
4. Generate content → sidebar should cover full screen
5. Quick actions → horizontal scroll works
6. Rotate to iPad (768px) → tablet layout
7. Rotate to desktop → normal layout

- [ ] **Step 9: Commit**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add static/style.css templates/index.html static/script.js && git commit -m "feat: add responsive mobile layout with bottom tab bar and TOC dropdown"
```

---
### Task 6: Animation System

**Files:**
- Modify: `static/style.css` (keyframes, transition classes)
- Modify: `static/script.js` (sidebar animation, streaming enhancement, toast animation)

**Interfaces:**
- Consumes: existing CSS classes and JS functions
- Produces: animated tab switches, cards, buttons, sidebar, modals, streaming feedback, toasts

- [ ] **Step 1: Add L1 CSS transitions**

Insert before the first `@media` in `/Users/wuqqi/math-modeling-assistant/static/style.css`:
```css
/* ============================================================
   Animation System — L1: CSS Transitions
   ============================================================ */

/* Tab content switch */
.tab {
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.2s ease-out, transform 0.2s ease-out;
  pointer-events: none;
}
.tab.active {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

/* Card hover lift */
.card, .model-card, .viz-template, .tool-card {
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.card:hover, .model-card:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-lg);
}

/* Button press feedback */
.btn-primary:active, .btn-sm:active, .btn-secondary:active {
  transform: scale(0.97);
  transition: transform 0.1s ease;
}

/* Model card glow on hover */
.model-card {
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.model-card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

/* Nav button */
.nav-btn {
  transition: color 0.15s ease, background 0.15s ease;
}

/* Result card reveal */
.result-card.visible {
  animation: fadeSlideUp 0.4s ease-out;
}
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 2: Add L2 sidebar & modal animations**

Append:
```css
/* ============================================================
   Animation System — L2: Sidebar & Modal
   ============================================================ */

/* Sidebar slide-in */
.result-sidebar {
  transform: translateX(100%);
  transition: transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}
.result-sidebar.open {
  transform: translateX(0);
}

/* Sidebar backdrop */
.result-sidebar-backdrop {
  opacity: 0;
  transition: opacity 0.25s ease;
  pointer-events: none;
}
.result-sidebar-backdrop.open {
  opacity: 1;
  pointer-events: auto;
}

/* Explain panel */
.explain-panel {
  animation: slideUp 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Modal entrance */
@keyframes modalIn {
  from { opacity: 0; transform: scale(0.95); }
  to   { opacity: 1; transform: scale(1); }
}

/* Overlay fade */
.overlay {
  animation: fadeIn 0.2s ease;
}
@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}

/* Paper stats slide down */
.paper-stats {
  animation: slideDown 0.35s ease-out;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-10px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 3: Add L3 streaming animations**

Append:
```css
/* ============================================================
   Animation System — L3: Streaming Generation
   ============================================================ */

/* Stage indicator pulse */
.stage-indicator .stage-dot {
  display: inline-block; width: 8px; height: 8px;
  border-radius: 50%; background: var(--accent);
  animation: pulse 1.4s ease-in-out infinite;
  margin-right: 8px; vertical-align: middle;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.3; transform: scale(0.75); }
}

/* Streaming cursor blink */
.streaming-cursor::after {
  content: '|'; color: var(--accent);
  animation: blink 1s step-end infinite;
  font-weight: 700;
}
@keyframes blink {
  50% { opacity: 0; }
}

/* Content fade-in for new paragraphs */
.markdown-body > * {
  animation: contentFadeIn 0.3s ease-out;
}
@keyframes contentFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Skeleton loading shimmer */
.skeleton {
  background: linear-gradient(90deg, var(--border) 25%, transparent 50%, var(--border) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: var(--radius-sm);
  height: 16px; margin: 8px 0;
}
@keyframes shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Completion glow */
.result-card.completed {
  animation: glowPulse 2s ease-out;
}
@keyframes glowPulse {
  0%   { box-shadow: 0 0 0 0 var(--accent-glow); }
  50%  { box-shadow: 0 0 0 8px var(--accent-glow); }
  100% { box-shadow: 0 0 0 0 transparent; }
}
```

- [ ] **Step 4: Add L4 micro-interactions**

Append:
```css
/* ============================================================
   Animation System — L4: Micro-interactions
   ============================================================ */

/* Toast slide-in */
.toast {
  animation: toastIn 0.3s ease-out;
}
.toast.hiding {
  animation: toastOut 0.25s ease-in forwards;
}
@keyframes toastIn {
  from { opacity: 0; transform: translateY(-12px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes toastOut {
  from { opacity: 1; transform: translateY(0); }
  to   { opacity: 0; transform: translateY(-12px); }
}

/* Star/favorite pop */
.history-item-star.starred {
  animation: starPop 0.3s ease;
}
@keyframes starPop {
  0%   { transform: scale(1); }
  50%  { transform: scale(1.35); }
  100% { transform: scale(1); }
}

/* Copy button feedback */
.copy-done {
  animation: copyPop 0.3s ease;
  color: var(--green);
}
@keyframes copyPop {
  0%   { transform: scale(1); }
  50%  { transform: scale(1.2); }
  100% { transform: scale(1); }
}

/* Verification checklist item toggle */
.verify-item {
  transition: background 0.2s ease, border-color 0.2s ease;
}

/* History item hover */
.history-item {
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.history-item:hover {
  transform: translateX(4px);
}

/* Viz template expand */
.viz-template[open] .viz-template-body {
  animation: expandDown 0.2s ease;
}
@keyframes expandDown {
  from { opacity: 0; max-height: 0; }
  to   { opacity: 1; max-height: 1000px; }
}

/* Edit textarea focus */
.edit-textarea:focus {
  transition: box-shadow 0.2s ease;
  box-shadow: 0 0 0 3px var(--accent-glow);
}
```

- [ ] **Step 5: Update JS for streaming completion animation**

In script.js, find where `injectQuickActions()` or `injectCodeCopyButtons()` is called after streaming finishes (around line 668-680 for generator, line 940-950 for paper). After the final render, add:
```javascript
// Completion animation
resultContent.classList.add('completed');
setTimeout(() => resultContent.classList.remove('completed'), 2500);
```

And update the `showToast` function to support animation out:
```javascript
function showToast(msg) {
  const existing = document.querySelector('.toast');
  if (existing) { existing.remove(); }
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('hiding');
    toast.addEventListener('animationend', () => toast.remove());
  }, 3000);
}
```

Verify the existing `showToast` function in script.js and replace it with the above version if different.

- [ ] **Step 6: Update copy button feedback in JS**

Find all copy button handlers (`injectCodeCopyButtons`, `copyDedupResult`, etc.) and add animation:
```javascript
// After successful copy:
btn.classList.add('copy-done');
btn.textContent = '已复制!';
setTimeout(() => {
  btn.classList.remove('copy-done');
  btn.textContent = originalText;
}, 1500);
```

- [ ] **Step 7: Test animations**

1. Tab switching: click between tabs → smooth fade+slide up
2. Generate: watch stage indicator pulse + content fade in + completion glow
3. Sidebar: open plagiarism check → slide in from right
4. Modal: open settings → scale+fade in
5. Cards: hover → lift + glow
6. Toast: after any action → slide in top, slide out after 3s
7. Buttons: click → scale down press

- [ ] **Step 8: Commit**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add static/style.css static/script.js && git commit -m "feat: add comprehensive 4-layer animation system"
```

---
### Task 7: Desktop Build Script

**Files:**
- Create: `build.py`

**Interfaces:**
- Consumes: `win_build.spec`, `mac_build.spec`, `launcher.py`, `launcher_win.pyw`
- Produces: single-file executable in `dist/`

- [ ] **Step 1: Create build.py**

Create `/Users/wuqqi/math-modeling-assistant/build.py`:
```python
#!/usr/bin/env python3
"""One-command build script for Math Modeling Assistant desktop app.

Usage:
    python build.py           # Build for current platform
    python build.py --clean   # Clean previous builds first

Output:
    dist/MathModelingAssistant.exe     (Windows)
    dist/MathModelingAssistant.app     (macOS)
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "MathModelingAssistant"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def clean():
    """Remove previous build artifacts."""
    for d in [BUILD, DIST]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  Cleaned {d.name}/")
    for spec in ROOT.glob("*.spec"):
        pass  # Keep spec files


def build_windows():
    """Build Windows .exe using PyInstaller."""
    spec = ROOT / "win_build.spec"
    if not spec.exists():
        print(f"ERROR: {spec} not found")
        sys.exit(1)
    print("[1/2] Running PyInstaller for Windows...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(DIST), "--workpath", str(BUILD), str(spec)],
        cwd=str(ROOT), capture_output=False,
    )
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed")
        sys.exit(1)

    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"  OK {exe.relative_to(ROOT)} ({size_mb:.1f} MB)")
    else:
        print("WARNING: .exe not found at expected path")


def build_macos():
    """Build macOS .app using PyInstaller."""
    spec = ROOT / "mac_build.spec"
    if not spec.exists():
        print(f"ERROR: {spec} not found")
        sys.exit(1)
    print("[1/2] Running PyInstaller for macOS...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(DIST), "--workpath", str(BUILD), str(spec)],
        cwd=str(ROOT), capture_output=False,
    )
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed")
        sys.exit(1)

    app = DIST / f"{APP_NAME}.app"
    if app.exists():
        print(f"  OK {app.relative_to(ROOT)}")
    else:
        print("WARNING: .app not found at expected path")


def main():
    system = platform.system()
    print(f"=== MMA Desktop Builder ({system}) ===")
    print()

    if "--clean" in sys.argv:
        clean()

    # Ensure PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    if system == "Windows":
        build_windows()
    elif system == "Darwin":
        build_macos()
    else:
        print(f"Unsupported platform: {system}")
        print("This build script supports Windows and macOS only.")
        sys.exit(1)

    print()
    print("=== Done ===")
    out = DIST / APP_NAME if system == "Windows" else DIST / f"{APP_NAME}.app"
    print(f"Output: {out}")
    print("To distribute: zip the output folder and share.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test build script (dry run)**

```bash
cd /Users/wuqqi/math-modeling-assistant && python3 build.py --help 2>&1 || python3 -c "import build; print('build.py syntax OK')"
```
Expected: build.py syntax OK

- [ ] **Step 3: Commit**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add build.py && git commit -m "feat: add unified build script for Windows and macOS"
```

---
### Task 8: Dark Mode Verification & Final Integration

**Files:**
- Modify: `static/style.css` (dark mode selectors for all new components)
- Verify: all 12 files

**Interfaces:**
- Consumes: all Tasks 1-7
- Produces: fully dark-mode-compatible app, ready for Railway deploy

- [ ] **Step 1: Verify dark mode coverage for all new CSS**

Check that every new CSS class has a `[data-theme="dark"]` variant or uses `var(--*)` tokens that already have dark definitions. The following variables already have dark mode values:
- `--surface`, `--border`, `--text`, `--text-secondary`, `--accent`, `--accent-glow`, `--accent-light`, `--green`, `--amber`, `--red`, `--overlay-bg`

All new CSS uses these variables, so dark mode should work automatically. However, verify these specific elements:

```css
/* Additional dark mode overrides if needed */
[data-theme="dark"] .setup-card { border-color: var(--border); }
[data-theme="dark"] .pwa-install-banner { background: var(--surface); }
[data-theme="dark"] .toc-dropdown-btn { background: var(--surface); }
[data-theme="dark"] .toc-dropdown { background: var(--surface); }
[data-theme="dark"] .bottom-nav { background: var(--surface); }
[data-theme="dark"] .offline-page { background: var(--bg); color: var(--text); }
```

Append these if not already covered by the existing CSS.

- [ ] **Step 2: Manual dark mode test**

1. Start Flask: `python app.py`
2. Open http://localhost:8080 → toggle dark mode (moon icon)
3. Check each tab: Generator, Paper, Models, Problems, Guide, Roles
4. Check setup modal in dark mode
5. Generate content → check result card, sidebar, explain panel, quick actions
6. Check PWA install banner in dark mode
7. Check toast in dark mode
8. All text must be readable, no white-on-white or black-on-black

- [ ] **Step 3: Mobile responsive final check**

1. Chrome DevTools Device Mode → iPhone 12
2. Dark mode ON
3. Navigate all tabs
4. Generate content → verify all features work
5. Sidebar opens fullscreen
6. Quick actions scrolls horizontally
7. Bottom tab bar switches tabs correctly

- [ ] **Step 4: Railway deployment**

1. Install Railway CLI: `brew install railway` (macOS) or `npm i -g @railway/cli`
2. Login: `railway login`
3. Link project: `cd /Users/wuqqi/math-modeling-assistant && railway init`
4. Set environment variable in Railway dashboard: `DEEPSEEK_API_KEY` (optional — users can bring their own)
5. Deploy: `railway up`
6. Test: open the Railway URL on phone and desktop

- [ ] **Step 5: Final git push**

```bash
cd /Users/wuqqi/math-modeling-assistant && git add -A && git status
# Verify only intended files are staged
git commit -m "feat: dark mode verification and final integration for deployment UX overhaul"
git push origin main
```

- [ ] **Step 6: Push to Railway**

```bash
cd /Users/wuqqi/math-modeling-assistant && railway up
```

Expected: deployment URL shown, app accessible from any device.

---

