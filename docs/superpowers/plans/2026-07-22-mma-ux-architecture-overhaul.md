# MMA UX & Architecture Overhaul — Implementation Plan

> **For agentic workers:** Execute inline, testing each task before moving on.

**Goal:** Transform MMA with AI teammate panel, progress transparency, user accounts, SQLite persistence, voice input, and maintainable code structure.

**Architecture:** Flask monolith + SQLite + vanilla JS (split into 9 files) + flask-login + cryptography. AI teammate with auto-switching roles. Stage-based progress cards.

**Tech Stack:** Flask 3.x, SQLite, vanilla HTML/CSS/JS, flask-login, cryptography, Web Speech API

## Global Constraints

- Zero new frontend frameworks — vanilla HTML/CSS/JS only
- Zero build steps — no bundler, no transpiler, no npm
- All existing features preserved — no regression
- PWA continues working
- Railway single-container deployment unchanged
- Desktop build still works — detect offline mode, skip auth
- SQLite only — no PostgreSQL
- Voice input uses Web Speech API only
- All teammate suggestions use keyword matching (not LLM) for <200ms response
- Chinese-first UI language

---

### Task 1: Database Layer + Auth Backend

**Files:**
- Create: `src/db.py`
- Create: `src/auth.py`
- Modify: `requirements.txt`
- Modify: `app.py` (register auth blueprint)

**Interfaces:**
- Produces: `get_db()` → sqlite3.Connection, `init_db()`, `User` class with `create/authenticate/change_password`, `auth_bp` Blueprint with `/api/auth/register`, `/api/auth/login`, `/api/auth/logout`

- [ ] **Step 1: Add dependencies to requirements.txt**

```
flask-login>=0.6.0
cryptography>=41.0.0
```

Run: `pip install flask-login cryptography`

- [ ] **Step 2: Create src/db.py**

```python
"""SQLite database layer for MMA."""
import sqlite3
import os

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DB_PATH = os.path.join(DB_DIR, 'mma.db')


def get_db() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            encrypted_api_key TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES user(id),
            contest_type TEXT,
            problem_type TEXT,
            problem_text TEXT,
            result_content TEXT,
            content_type TEXT DEFAULT 'framework',
            starred INTEGER DEFAULT 0,
            tags TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES user(id),
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    print(f"[DB] Initialized at {DB_PATH}")
```

- [ ] **Step 3: Create src/auth.py**

```python
"""Authentication: register, login, logout."""
import uuid
import os
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Blueprint, request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from .db import get_db, init_db

auth_bp = Blueprint('auth', __name__)

# Encryption for API keys
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', '')
if ENCRYPTION_KEY:
    _fernet = Fernet(ENCRYPTION_KEY.encode() if len(ENCRYPTION_KEY) == 44
                     else Fernet.generate_key())
else:
    _fernet = None


def encrypt_api_key(plain_key: str) -> str:
    if not plain_key or not _fernet:
        return ''
    return _fernet.encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    if not encrypted or not _fernet:
        return ''
    try:
        return _fernet.decrypt(encrypted.encode()).decode()
    except Exception:
        return ''


def _generate_token() -> str:
    return uuid.uuid4().hex


def _get_user_by_token(token: str):
    conn = get_db()
    row = conn.execute(
        "SELECT u.id, u.email, u.encrypted_api_key FROM user u "
        "JOIN session s ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token, datetime.now(timezone.utc).isoformat())
    ).fetchone()
    conn.close()
    return row


def get_current_user():
    """Get current user from cookie token."""
    token = request.cookies.get('mma_session', '')
    if not token:
        return None
    return _get_user_by_token(token)


def login_required(f):
    """Decorator for API routes that require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': '请先登录'}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or '@' not in email:
        return jsonify({'error': '请输入有效邮箱'}), 400
    if len(password) < 6:
        return jsonify({'error': '密码至少 6 位'}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM user WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': '该邮箱已注册'}), 409

    password_hash = generate_password_hash(password)
    conn.execute("INSERT INTO user (email, password_hash) VALUES (?, ?)",
                 (email, password_hash))
    conn.commit()
    user_id = conn.execute("SELECT id FROM user WHERE email = ?", (email,)).fetchone()['id']

    # Auto-login after register
    token = _generate_token()
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn.execute("INSERT INTO session (user_id, token, expires_at) VALUES (?, ?, ?)",
                 (user_id, token, expires))
    conn.commit()
    conn.close()

    resp = jsonify({'status': 'ok', 'email': email})
    resp.set_cookie('mma_session', token, max_age=86400*7, httponly=True,
                    secure=False, samesite='Lax')
    return resp


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    conn = get_db()
    user = conn.execute("SELECT id, password_hash FROM user WHERE email = ?",
                        (email,)).fetchone()
    if not user or not check_password_hash(user['password_hash'], password):
        conn.close()
        return jsonify({'error': '邮箱或密码错误'}), 401

    token = _generate_token()
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn.execute("INSERT INTO session (user_id, token, expires_at) VALUES (?, ?, ?)",
                 (user['id'], token, expires))
    conn.commit()
    conn.close()

    resp = jsonify({'status': 'ok', 'email': email})
    resp.set_cookie('mma_session', token, max_age=86400*7, httponly=True,
                    secure=False, samesite='Lax')
    return resp


@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    token = request.cookies.get('mma_session', '')
    if token:
        conn = get_db()
        conn.execute("DELETE FROM session WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    resp = jsonify({'status': 'ok'})
    resp.delete_cookie('mma_session')
    return resp


@auth_bp.route('/api/auth/me', methods=['GET'])
def me():
    user = get_current_user()
    if not user:
        return jsonify({'logged_in': False})
    return jsonify({
        'logged_in': True,
        'email': user['email'],
        'has_api_key': bool(user['encrypted_api_key']),
    })


@auth_bp.route('/api/auth/save-key', methods=['POST'])
@login_required
def save_key():
    data = request.get_json() or {}
    api_key = data.get('api_key', '').strip()
    if not api_key or not api_key.startswith('sk-'):
        return jsonify({'error': 'Key 格式不正确'}), 400

    encrypted = encrypt_api_key(api_key)
    conn = get_db()
    conn.execute("UPDATE user SET encrypted_api_key = ? WHERE id = ?",
                 (encrypted, g.current_user['id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@auth_bp.route('/api/auth/get-key', methods=['GET'])
@login_required
def get_key():
    user = g.current_user
    decrypted = decrypt_api_key(user['encrypted_api_key'])
    return jsonify({'api_key': decrypted[:8] + '***' if decrypted else ''})
```

- [ ] **Step 4: Wire auth blueprint into app.py**

Add to app.py near other imports:
```python
from src.auth import auth_bp, get_current_user
app.register_blueprint(auth_bp)
```

Also add a fallback `_get_api_key()` that tries user's saved key first:
```python
def _get_api_key():
    header_key = request.headers.get("X-API-Key", "").strip()
    if header_key:
        return header_key
    # Try server-side stored key
    user = get_current_user()
    if user and user['encrypted_api_key']:
        from src.auth import decrypt_api_key
        key = decrypt_api_key(user['encrypted_api_key'])
        if key:
            return key
    # Fallback: env var for desktop builds
    import os
    return os.environ.get("DEEPSEEK_API_KEY", "")
```

- [ ] **Step 5: Test auth flow manually**

```bash
# Start the app
cd /Users/wuqqi/math-modeling-assistant && python app.py &
sleep 2

# Test register
curl -X POST http://localhost:8080/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"123456"}' -c /tmp/cookies.txt

# Test me
curl http://localhost:8080/api/auth/me -b /tmp/cookies.txt

# Test save key
curl -X POST http://localhost:8080/api/auth/save-key \
  -H "Content-Type: application/json" \
  -d '{"api_key":"sk-test123456789"}' -b /tmp/cookies.txt

# Test logout
curl -X POST http://localhost:8080/api/auth/logout -b /tmp/cookies.txt
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/db.py src/auth.py app.py
git commit -m "feat: add SQLite database layer and auth backend"
```

---

### Task 2: Auth Templates + Frontend JS

**Files:**
- Create: `templates/login.html`
- Create: `templates/register.html`
- Modify: `templates/index.html` (add login/register links)
- Create: `static/js/auth.js`
- Modify: `app.py` (add page routes for login/register)

- [ ] **Step 1: Add page routes to app.py**

```python
@app.route("/login")
def login_page():
    return render_template("login.html")

@app.route("/register")
def register_page():
    return render_template("register.html")
```

- [ ] **Step 2: Create templates/login.html**

```html
<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 — MMA</title>
<link rel="stylesheet" href="/static/style.css">
<script>try{var t=localStorage.getItem('mma-theme')||(window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');document.documentElement.setAttribute('data-theme',t)}catch(e){}</script>
</head>
<body>
<main style="display:flex;align-items:center;justify-content:center;min-height:100vh">
<div class="card auth-card" style="width:100%;max-width:400px;padding:32px">
  <h1 style="text-align:center;margin-bottom:8px">MMA</h1>
  <p style="text-align:center;color:var(--text-secondary);margin-bottom:24px">Math Modeling Assistant</p>
  <form id="login-form" class="auth-form">
    <div class="field">
      <label for="login-email">邮箱</label>
      <input type="email" id="login-email" placeholder="your@email.com" required autofocus>
    </div>
    <div class="field">
      <label for="login-password">密码</label>
      <input type="password" id="login-password" placeholder="至少 6 位" required>
    </div>
    <div id="login-error" class="error-msg" hidden></div>
    <button type="submit" class="btn-primary" style="width:100%" id="login-btn">
      <span class="btn-text">登录</span>
      <span class="btn-loading" hidden><span class="spinner"></span>登录中...</span>
    </button>
  </form>
  <p style="text-align:center;margin-top:16px;font-size:14px;color:var(--text-secondary)">
    还没有账号？<a href="/register">注册</a>
  </p>
  <p style="text-align:center;font-size:13px;color:var(--text-secondary)">
    <a href="/">跳过，直接使用（不保存 Key）</a>
  </p>
</div>
</main>
<script src="/static/js/auth.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create templates/register.html** (similar to login, with confirm password field)

```html
<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>注册 — MMA</title>
<link rel="stylesheet" href="/static/style.css">
<script>try{var t=localStorage.getItem('mma-theme')||(window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');document.documentElement.setAttribute('data-theme',t)}catch(e){}</script>
</head>
<body>
<main style="display:flex;align-items:center;justify-content:center;min-height:100vh">
<div class="card auth-card" style="width:100%;max-width:400px;padding:32px">
  <h1 style="text-align:center;margin-bottom:8px">MMA</h1>
  <p style="text-align:center;color:var(--text-secondary);margin-bottom:24px">创建账号，同步你的 API Key 和生成记录</p>
  <form id="register-form" class="auth-form">
    <div class="field">
      <label for="reg-email">邮箱</label>
      <input type="email" id="reg-email" placeholder="your@email.com" required autofocus>
    </div>
    <div class="field">
      <label for="reg-password">密码</label>
      <input type="password" id="reg-password" placeholder="至少 6 位" required minlength="6">
    </div>
    <div class="field">
      <label for="reg-confirm">确认密码</label>
      <input type="password" id="reg-confirm" placeholder="再输入一次" required minlength="6">
    </div>
    <div id="reg-error" class="error-msg" hidden></div>
    <button type="submit" class="btn-primary" style="width:100%" id="reg-btn">
      <span class="btn-text">注册</span>
      <span class="btn-loading" hidden><span class="spinner"></span>注册中...</span>
    </button>
  </form>
  <p style="text-align:center;margin-top:16px;font-size:14px;color:var(--text-secondary)">
    已有账号？<a href="/login">登录</a>
  </p>
</div>
</main>
<script src="/static/js/auth.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create static/js/auth.js**

```javascript
// Auth page scripts (login / register)
(function() {
  const loginForm = document.getElementById('login-form');
  const regForm = document.getElementById('register-form');

  async function api(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return { status: res.status, data: await res.json() };
  }

  function setLoading(form, btnId, loading) {
    const btn = document.getElementById(btnId);
    btn.querySelector('.btn-text').hidden = loading;
    btn.querySelector('.btn-loading').hidden = !loading;
    btn.disabled = loading;
  }

  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('login-email').value.trim();
      const password = document.getElementById('login-password').value;
      const errorEl = document.getElementById('login-error');

      if (!email || !password) {
        errorEl.textContent = '请填写邮箱和密码'; errorEl.hidden = false; return;
      }

      setLoading(loginForm, 'login-btn', true);
      errorEl.hidden = true;

      const { status, data } = await api('/api/auth/login', { email, password });
      setLoading(loginForm, 'login-btn', false);

      if (status === 200) {
        // Sync localStorage API key to server
        const localKey = localStorage.getItem('mma-api-key');
        if (localKey && localKey.startsWith('sk-')) {
          await api('/api/auth/save-key', { api_key: localKey });
        }
        window.location.href = '/';
      } else {
        errorEl.textContent = data.error || '登录失败';
        errorEl.hidden = false;
      }
    });
  }

  if (regForm) {
    regForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('reg-email').value.trim();
      const password = document.getElementById('reg-password').value;
      const confirm = document.getElementById('reg-confirm').value;
      const errorEl = document.getElementById('reg-error');

      if (!email || !password) {
        errorEl.textContent = '请填写邮箱和密码'; errorEl.hidden = false; return;
      }
      if (password !== confirm) {
        errorEl.textContent = '两次密码不一致'; errorEl.hidden = false; return;
      }
      if (password.length < 6) {
        errorEl.textContent = '密码至少 6 位'; errorEl.hidden = false; return;
      }

      setLoading(regForm, 'reg-btn', true);
      errorEl.hidden = true;

      const { status, data } = await api('/api/auth/register', { email, password });
      setLoading(regForm, 'reg-btn', false);

      if (status === 200) {
        const localKey = localStorage.getItem('mma-api-key');
        if (localKey && localKey.startsWith('sk-')) {
          await api('/api/auth/save-key', { api_key: localKey });
        }
        window.location.href = '/';
      } else {
        errorEl.textContent = data.error || '注册失败';
        errorEl.hidden = false;
      }
    });
  }
})();
```

- [ ] **Step 5: Add user menu to index.html nav**

In `index.html`, add to the nav (after theme-toggle btn):
```html
<a href="/login" id="login-link" class="nav-login-link">登录</a>
<span id="user-menu" class="user-menu" hidden>
  <span id="user-email-display"></span>
  <button id="logout-btn" class="btn-sm">退出</button>
</span>
```

Load `auth.js` in index.html (first, before other scripts):
```html
<script src="/static/js/auth.js"></script>
```

- [ ] **Step 6: Commit**

```bash
git add templates/login.html templates/register.html templates/index.html static/js/auth.js app.py
git commit -m "feat: add login/register pages and auth frontend"
```

---

### Task 3: JS File Split

**Files:**
- Create: `static/js/lib.js`
- Create: `static/js/app.js`
- Create: `static/js/generator.js`
- Create: `static/js/paper.js`
- Create: `static/js/models.js`
- Create: `static/js/problems.js`
- Create: `static/js/guide.js`
- Modify: `templates/index.html` (load split JS files)
- Keep: `static/script.js` (until all verified, then remove)

**Approach:** Extract from script.js into separate files by function grouping. Keep all variable names and function signatures identical.

- [ ] **Step 1: Create static/js/lib.js** — Move shared utilities

Extract: `escapeHtml()`, `showToast()`, `ensureList()`, `markdown` config, `copyToClipboard()`

- [ ] **Step 2: Create static/js/app.js** — Move init code

Extract: Theme code, tab switching, keyboard shortcuts, preload, onboarding banner, `API_KEY_STORAGE`, `getApiKey()`, `setApiKey()`, `hasApiKey()`, `showSetupModal()`, `hideSetupModal()`, `verifyAndSaveKey()`, fetch override, `checkFirstVisit()`

- [ ] **Step 3: Create static/js/generator.js** — Move generator tab

Extract: `generateBtn`, stream handling, `cancelGen()`, `_activeController`, result rendering, history management, `syncGeneratorToPaper()`

- [ ] **Step 4: Create static/js/paper.js** — Move paper tab

Extract: Paper generation, TOC builder, analysis tools (verify-references, verify-math, check-plagiarism, deduplicate, score-paper, etc.), paper history

- [ ] **Step 5: Create static/js/models.js** — Move models tab

Extract: `loadModels()`, `filterModels()`, `renderModelGrid()`, `showModelDetail()`, comparison

- [ ] **Step 6: Create static/js/problems.js** — Move problems tab

Extract: `loadProblems()`, `renderProblemList()`, `useProblem()`, bookmarks

- [ ] **Step 7: Create static/js/guide.js** — Move guide tab

Extract: `loadGuide()`, timeline render, tools render, viz templates, paper upload/analysis

- [ ] **Step 8: Update index.html script loading**

Replace `<script src="/static/script.js"></script>` with:
```html
<script src="/static/js/lib.js"></script>
<script src="/static/js/auth.js"></script>
<script src="/static/js/app.js"></script>
<script src="/static/js/generator.js"></script>
<script src="/static/js/paper.js"></script>
<script src="/static/js/models.js"></script>
<script src="/static/js/problems.js"></script>
<script src="/static/js/guide.js"></script>
```

- [ ] **Step 9: Test all tabs load without errors**

Open `http://localhost:8080` in browser, check console for no errors. Test each tab.

- [ ] **Step 10: Remove old script.js and commit**

```bash
git rm static/script.js
git add static/js/ templates/index.html
git commit -m "refactor: split script.js into 8 modular files"
```

---

### Task 4: API Key Encryption + History Migration

**Files:**
- Modify: `static/js/app.js` (add server history sync)
- Create: `src/routes/history.py`
- Modify: `app.py` (register history blueprint)

- [ ] **Step 1: Create src/routes/history.py**

```python
"""History CRUD API routes."""
from flask import Blueprint, request, jsonify, g
from src.auth import login_required, get_current_user
from src.db import get_db
import json

history_bp = Blueprint('history', __name__)


@history_bp.route('/api/history', methods=['GET'])
def list_history():
    user = get_current_user()
    if not user:
        return jsonify({'history': []})

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM history WHERE user_id = ? ORDER BY updated_at DESC LIMIT 50",
        (user['id'],)
    ).fetchall()
    conn.close()

    return jsonify({'history': [
        {k: row[k] for k in row.keys()} for row in rows
    ]})


@history_bp.route('/api/history', methods=['POST'])
@login_required
def save_history():
    data = request.get_json() or {}
    content_type = data.get('content_type', 'framework')

    conn = get_db()
    conn.execute(
        """INSERT INTO history (user_id, contest_type, problem_type, problem_text,
           result_content, content_type, tags)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (g.current_user['id'], data.get('contest_type', ''),
         data.get('problem_type', ''), data.get('problem_text', ''),
         data.get('result_content', ''), content_type,
         json.dumps(data.get('tags', []), ensure_ascii=False))
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute("SELECT * FROM history WHERE id = ?", (row_id,)).fetchone()
    conn.close()
    return jsonify({k: row[k] for k in row.keys()})


@history_bp.route('/api/history/<int:hid>', methods=['PUT'])
@login_required
def update_history(hid):
    data = request.get_json() or {}
    conn = get_db()

    updates = []
    params = []
    for field in ['starred', 'tags', 'contest_type', 'problem_type', 'result_content']:
        if field in data:
            updates.append(f"{field} = ?")
            val = data[field]
            if field == 'tags' and not isinstance(val, str):
                val = json.dumps(val, ensure_ascii=False)
            params.append(val)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.extend([hid, g.current_user['id']])
        conn.execute(
            f"UPDATE history SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
            params
        )
        conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@history_bp.route('/api/history/<int:hid>', methods=['DELETE'])
@login_required
def delete_history(hid):
    conn = get_db()
    conn.execute("DELETE FROM history WHERE id = ? AND user_id = ?",
                 (hid, g.current_user['id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@history_bp.route('/api/history/import', methods=['POST'])
@login_required
def import_history():
    """Import history from localStorage (migration)."""
    data = request.get_json() or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'imported': 0})

    conn = get_db()
    count = 0
    for item in items:
        conn.execute(
            """INSERT INTO history (user_id, contest_type, problem_type, problem_text,
               result_content, content_type, starred, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (g.current_user['id'], item.get('contest_type', ''),
             item.get('problem_type', ''), item.get('problem_text', ''),
             item.get('result_content', ''), item.get('content_type', 'framework'),
             item.get('starred', 0),
             json.dumps(item.get('tags', []), ensure_ascii=False))
        )
        count += 1
    conn.commit()
    conn.close()
    return jsonify({'imported': count})
```

- [ ] **Step 2: Register history blueprint in app.py**

```python
from src.routes.history import history_bp
app.register_blueprint(history_bp)
```

- [ ] **Step 3: Add server sync to frontend history functions**

In `static/js/app.js`, after successful generation, call:
```javascript
async function syncHistoryToServer(item) {
  try {
    await fetch('/api/history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contest_type: item.contest_type,
        problem_type: item.problem_type,
        problem_text: item.problem_text,
        result_content: item.result_content,
        content_type: item.content_type || 'framework',
        tags: item.tags || [],
      }),
    });
  } catch(e) { /* server sync is optional, don't block */ }
}
```

- [ ] **Step 4: Add import localStorage history on first login**

In `static/js/auth.js`, after successful login redirect:
```javascript
// Check for existing localStorage history to import
const localHistory = localStorage.getItem('mma-generator-history');
if (localHistory) {
  try {
    const items = JSON.parse(localHistory);
    await fetch('/api/history/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    });
  } catch(e) {}
}
```

- [ ] **Step 5: Test history CRUD**

```bash
# Login first
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"123456"}' -c /tmp/cookies.txt

# Create history
curl -X POST http://localhost:8080/api/history \
  -H "Content-Type: application/json" \
  -d '{"contest_type":"MCM/ICM","problem_type":"A","problem_text":"Test problem","result_content":"Test content"}' \
  -b /tmp/cookies.txt

# List history
curl http://localhost:8080/api/history -b /tmp/cookies.txt
```

- [ ] **Step 6: Commit**

```bash
git add src/routes/history.py app.py static/js/app.js static/js/auth.js
git commit -m "feat: add history CRUD with server-side persistence"
```

---

### Task 5: Backend Route Split

**Files:**
- Create: `src/routes/__init__.py`
- Create: `src/routes/generator_routes.py`
- Create: `src/routes/paper_routes.py`
- Create: `src/routes/models_routes.py`
- Create: `src/routes/problems_routes.py`
- Create: `src/routes/guide_routes.py`
- Create: `src/routes/context_hint.py`
- Modify: `app.py` (trim to factory + registration)

- [ ] **Step 1: Create src/routes/__init__.py** (empty)
- [ ] **Step 2: Move generator routes to src/routes/generator_routes.py** — `/api/generate`, `/api/generate/stream`, `/api/ai-report`, `/api/latex`
- [ ] **Step 3: Move paper routes to src/routes/paper_routes.py** — `/api/generate-paper/stream`, `/api/generate-paper/latex`, `/api/verify-references`, `/api/verify-math`, `/api/check-plagiarism`, `/api/deduplicate`, `/api/refine-abstract`, `/api/generate-sensitivity`, `/api/score-paper`, `/api/recommend-models`, `/api/suggest-figures`, `/api/compare-papers`, `/api/mock-review`, `/api/analyze-paper`, `/api/explain`
- [ ] **Step 4: Move models routes to src/routes/models_routes.py** — `/api/models`, `/api/models/<name>`
- [ ] **Step 5: Move problems routes to src/routes/problems_routes.py** — `/api/problems`
- [ ] **Step 6: Move guide routes to src/routes/guide_routes.py** — `/api/guide`, `/api/roles`
- [ ] **Step 7: Create src/routes/context_hint.py** — Keyword-matching hint engine

```python
"""Context-aware hint engine (keyword matching, NO LLM)."""
from flask import Blueprint, request, jsonify

context_hint_bp = Blueprint('context_hint', __name__)

# Hint templates keyed by problem_type keywords
HINTS = {
    'A': {  # Continuous
        'keywords': ['微分', '偏微分', '常微分', '优化', '连续', 'ode', 'pde', 'differential', 'continuous', 'calculus'],
        'hint': '这道题是连续型问题，常见建模路径：1) 微分方程描述动力学 2) 变分法优化 3) 有限元数值求解。建议从 ODE/PDE 入手。',
        'actions': [
            {'label': '推荐连续型模型', 'payload': 'recommend_continuous'},
            {'label': '查看微分方程示例', 'payload': 'show_pde_example'},
        ],
    },
    'B': {  # Discrete
        'keywords': ['离散', '整数规划', '组合', '调度', '路径', '图论', '离散事件', 'discrete', 'integer', 'combinatorial', 'scheduling'],
        'hint': '这是离散优化问题。推荐：整数规划 + 启发式算法（遗传算法/模拟退火）组合使用，先求精确解再全局寻优。',
        'actions': [
            {'label': '推荐离散模型', 'payload': 'recommend_discrete'},
            {'label': '查看遗传算法示例', 'payload': 'show_ga_example'},
        ],
    },
    'C': {  # Data Insights
        'keywords': ['数据', '预测', '分类', '回归', '聚类', '时间序列', '机器学习', 'data', 'prediction', 'classification', 'regression', 'clustering'],
        'hint': '数据洞察题！关键步骤：1) 数据清洗和探索性分析 2) 特征工程 3) 模型选择（从简单到复杂）4) 交叉验证。建议先用线性模型做 baseline。',
        'actions': [
            {'label': '推荐数据分析模型', 'payload': 'recommend_data'},
            {'label': '查看 EDA 代码模板', 'payload': 'show_eda_template'},
        ],
    },
    'D': {  # Network Science
        'keywords': ['网络', '图', '节点', '社交', '传播', 'network', 'graph', 'node', 'social'],
        'hint': '网络科学问题。核心思路：构建图模型 → 分析拓扑指标（度分布、聚类系数等）→ 应用网络算法（社区检测、最短路径等）。',
        'actions': [
            {'label': '推荐网络模型', 'payload': 'recommend_network'},
            {'label': '查看 NetworkX 示例', 'payload': 'show_networkx'},
        ],
    },
    'E': {  # Sustainability
        'keywords': ['环境', '可持续', '生态', '污染', '气候', '资源', 'environment', 'sustainability', 'climate', 'pollution'],
        'hint': '可持续性问题通常需要多目标优化。建议：先建立指标体系 → 再用 TOPSIS/AHP 综合评价 → 最后做情景分析。',
        'actions': [
            {'label': '推荐评价模型', 'payload': 'recommend_evaluation'},
            {'label': '查看 TOPSIS 示例', 'payload': 'show_topsis'},
        ],
    },
    'F': {  # Policy
        'keywords': ['政策', '经济', '社会', '管理', '评估', 'policy', 'economic', 'social'],
        'hint': '政策题重在论证逻辑。建议：1) 建立评价指标体系 2) 数据包络分析或层次分析法 3) 情景模拟和敏感性分析。',
        'actions': [
            {'label': '推荐政策分析模型', 'payload': 'recommend_policy'},
            {'label': '查看 AHP 示例', 'payload': 'show_ahp'},
        ],
    },
}

GENERAL_HINT = '准备好开始了吗？先在 Generator 填写题目信息，我会帮你分析问题类型并推荐合适的模型。'

INACTIVITY_HINT = '看起来你遇到困难了。需要我帮忙分析问题、推荐模型、或者解释某个概念吗？直接问我吧。'

COMPLETION_HINTS = [
    '框架已生成。建议检查"模型假设"部分是否包含了数据来源说明。',
    '生成完成！要不要我帮你验证一下参考文献的真实性？',
    '框架生成完毕。下一阶段可以生成完整论文，或者先做敏感性分析。',
]


@context_hint_bp.route('/api/context-hint', methods=['POST'])
def get_hint():
    data = request.get_json() or {}
    tab = data.get('tab', 'generator')
    problem_type = data.get('problem_type', '')
    problem_text = data.get('problem_text', '').lower()
    last_action = data.get('last_action', '')
    idle_seconds = data.get('idle_seconds', 0)

    hint_text = GENERAL_HINT
    actions = []

    # 1. Problem filled but not generated
    if tab == 'generator' and problem_text and last_action == 'problem_filled':
        type_info = HINTS.get(problem_type, {})
        if type_info:
            matched = any(kw in problem_text for kw in type_info.get('keywords', []))
            if matched:
                hint_text = type_info['hint']
                actions = type_info.get('actions', [])

    # 2. Generation just completed
    if last_action == 'generation_complete':
        import random
        hint_text = random.choice(COMPLETION_HINTS)
        actions = [
            {'label': '去检查', 'payload': 'open_paper_tab'},
            {'label': '继续生成完整论文', 'payload': 'generate_full_paper'},
        ]

    # 3. Inactivity
    if idle_seconds > 90:
        hint_text = INACTIVITY_HINT
        actions = [{'label': '帮我分析题目', 'payload': 'analyze_problem'}]

    # 4. Tab switch to models
    if tab == 'models' and last_action == 'tab_switch':
        type_info = HINTS.get(problem_type, {})
        hint_text = f'你正在处理{problem_type}题，以下是推荐模型。点击模型可查看详细说明和代码示例。'
        actions = [{'label': '自动筛选推荐模型', 'payload': 'filter_recommended'}]

    return jsonify({'hint_text': hint_text, 'actions': actions})
```

- [ ] **Step 8: Commit**

```bash
git add src/routes/ app.py
git commit -m "refactor: split backend routes into modular blueprints"
```

---

### Task 6: AI Teammate Panel (Frontend)

**Files:**
- Create: `static/js/ai-teammate.js`
- Modify: `templates/index.html` (add panel HTML + floating button)
- Modify: `static/style.css` (add teammate styles)

- [ ] **Step 1: Add panel HTML to index.html** (before `</body>`)

```html
<!-- AI Teammate -->
<button id="teammate-btn" class="teammate-float-btn" title="AI 队友">
  <span class="teammate-avatar">🧑‍💻</span>
  <span id="teammate-badge" class="teammate-badge" hidden>0</span>
</button>

<div id="teammate-panel" class="teammate-panel" hidden>
  <div class="teammate-header">
    <span id="teammate-role-icon">🧑‍💻</span>
    <span id="teammate-role-name">建模手</span>
    <button id="teammate-close" class="teammate-close">&times;</button>
  </div>
  <div id="teammate-messages" class="teammate-messages"></div>
  <div class="teammate-input-row">
    <button id="teammate-mic-btn" class="teammate-mic-btn" title="语音输入" hidden>🎤</button>
    <input type="text" id="teammate-input" class="teammate-input" placeholder="问队友...">
    <button id="teammate-send" class="teammate-send-btn">发送</button>
  </div>
</div>
```

- [ ] **Step 2: Add teammate CSS to style.css** (append)

```css
/* AI Teammate Panel */
.teammate-float-btn {
  position: fixed; bottom: 24px; right: 24px; z-index: 1000;
  width: 56px; height: 56px; border-radius: 50%; border: none;
  background: var(--accent); color: #fff; font-size: 24px;
  cursor: pointer; box-shadow: var(--shadow-lg);
  display: flex; align-items: center; justify-content: center;
  transition: transform .2s, opacity .3s, box-shadow .2s;
}
.teammate-float-btn:hover { transform: scale(1.1); box-shadow: 0 8px 25px var(--accent-glow); }
.teammate-float-btn.scrolling { opacity: 0.5; }

.teammate-badge {
  position: absolute; top: -4px; right: -4px;
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--red); color: #fff; font-size: 11px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 600;
}

.teammate-panel {
  position: fixed; bottom: 92px; right: 24px; z-index: 999;
  width: 380px; max-height: 520px; background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow-lg); display: flex; flex-direction: column;
  animation: teammateSlideIn .3s ease-out;
  overflow: hidden;
}
@keyframes teammateSlideIn {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

.teammate-header {
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 8px;
  font-weight: 600; font-size: 14px;
}
.teammate-close { margin-left: auto; background: none; border: none; font-size: 18px; cursor: pointer; color: var(--text-secondary); }

.teammate-messages {
  flex: 1; overflow-y: auto; padding: 12px;
  display: flex; flex-direction: column; gap: 10px;
  max-height: 340px;
}
.teammate-message {
  max-width: 85%; padding: 10px 14px; border-radius: 14px;
  font-size: 13px; line-height: 1.55; animation: msgIn .2s ease-out;
}
@keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.teammate-message.role-teammate { background: var(--inline-code-bg); align-self: flex-start; border-bottom-left-radius: 4px; }
.teammate-message.role-user { background: var(--accent); color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
.teammate-message .msg-actions { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
.teammate-message .msg-btn {
  padding: 4px 10px; border-radius: 14px; border: 1px solid var(--accent);
  background: transparent; color: var(--accent); font-size: 12px;
  cursor: pointer; transition: background .15s;
}
.teammate-message .msg-btn:hover { background: var(--accent-light); }

.teammate-input-row {
  padding: 10px 12px; border-top: 1px solid var(--border);
  display: flex; gap: 8px; align-items: center;
}
.teammate-input {
  flex: 1; border: 1px solid var(--border); border-radius: 20px;
  padding: 8px 14px; font-size: 13px; background: var(--bg);
  color: var(--text); outline: none;
}
.teammate-input:focus { border-color: var(--accent); }
.teammate-send-btn {
  background: var(--accent); color: #fff; border: none;
  border-radius: 50%; width: 36px; height: 36px; cursor: pointer;
  font-size: 14px; flex-shrink: 0;
}
.teammate-mic-btn {
  background: none; border: none; font-size: 18px; cursor: pointer;
  padding: 4px; flex-shrink: 0; opacity: 0.7;
}
.teammate-mic-btn.recording { color: var(--red); opacity: 1; animation: pulse 1s infinite; }
.teammate-mic-btn:disabled { opacity: 0.3; cursor: default; }

/* Mobile: bottom sheet */
@media (max-width: 768px) {
  .teammate-panel {
    position: fixed; bottom: 0; left: 0; right: 0; width: 100%;
    max-height: 70vh; border-radius: var(--radius) var(--radius) 0 0;
    animation: sheetUp .3s ease-out;
  }
  @keyframes sheetUp {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
  }
  .teammate-float-btn { bottom: 80px; right: 16px; }
  .teammate-mic-btn { display: inline-block !important; }
}
```

- [ ] **Step 3: Create static/js/ai-teammate.js**

Core logic:
- `Teammate` object with `open()`, `close()`, `addMessage(role, text, actions)`
- `showHint(hintData)` — displays proactive hint with action buttons
- `updateRole(tabName)` — switches role icon/name per tab
- `onTabSwitch(tabName)` — triggers context-hint API call
- `typewriterEffect(el, text, speed)` — 30ms/char, skippable on click
- Scroll listener that adds/removes `.scrolling` class on float button
- Send button: calls LLM with proper system prompt for current role
- Role system prompts inline (short, focused)

```javascript
// AI Teammate — floating panel with role-switching
(function() {
  const ROLE_CONFIG = {
    generator: { name: '建模手', icon: '📐', systemPrompt: '你是数学建模竞赛的建模手，擅长分析问题、推荐模型、构建数学框架。用简洁中文回答，每次不超过 150 字。' },
    paper: { name: '写作手', icon: '✍️', systemPrompt: '你是数学建模竞赛的写作手，擅长论文结构、学术表达、图表设计。用简洁中文回答，每次不超过 150 字。' },
    models: { name: '建模手', icon: '📐', systemPrompt: '你是数学建模专家，擅长解释模型原理和适用场景。用生活类比帮助理解。' },
    problems: { name: '建模手', icon: '📐', systemPrompt: '你是数学建模专家，擅长分析竞赛真题的解题思路。' },
    guide: { name: '教练', icon: '🎯', systemPrompt: '你是竞赛教练，帮助团队规划时间、检查进度、提醒注意事项。' },
    roles: { name: '教练', icon: '🎯', systemPrompt: '你是竞赛教练，帮助三位队员明确分工和协作要点。' },
  };

  let currentRole = 'generator';
  let panelOpen = false;
  let unreadCount = 0;

  const btn = document.getElementById('teammate-btn');
  const panel = document.getElementById('teammate-panel');
  const messagesEl = document.getElementById('teammate-messages');
  const inputEl = document.getElementById('teammate-input');
  const badge = document.getElementById('teammate-badge');
  const roleIcon = document.getElementById('teammate-role-icon');
  const roleName = document.getElementById('teammate-role-name');

  function updateRole(tabName) {
    const config = ROLE_CONFIG[tabName] || ROLE_CONFIG.generator;
    currentRole = tabName;
    if (roleIcon) roleIcon.textContent = config.icon;
    if (roleName) roleName.textContent = config.name;
    if (btn) btn.querySelector('.teammate-avatar').textContent = config.icon;
  }

  function addMessage(role, text, actions) {
    const el = document.createElement('div');
    el.className = `teammate-message role-${role}`;
    el.innerHTML = `<div class="msg-text">${text}</div>`;
    if (actions && actions.length) {
      el.innerHTML += `<div class="msg-actions">${actions.map(a =>
        `<button class="msg-btn" data-payload="${a.payload}">${a.label}</button>`
      ).join('')}</div>`;
    }
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    if (!panelOpen && role === 'teammate') {
      unreadCount++;
      badge.textContent = unreadCount;
      badge.hidden = false;
    }
  }

  function open() {
    panel.hidden = false;
    panelOpen = true;
    unreadCount = 0;
    badge.hidden = true;
    inputEl.focus();
  }

  function close() {
    panel.hidden = true;
    panelOpen = false;
  }

  async function fetchHint(context) {
    try {
      const res = await fetch('/api/context-hint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(context),
      });
      const data = await res.json();
      if (data.hint_text) addMessage('teammate', data.hint_text, data.actions);
    } catch(e) {}
  }

  btn.addEventListener('click', () => panelOpen ? close() : open());
  document.getElementById('teammate-close').addEventListener('click', close);

  // Scroll detection
  let scrollTimer;
  window.addEventListener('scroll', () => {
    btn.classList.add('scrolling');
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => btn.classList.remove('scrolling'), 200);
  }, { passive: true });

  // Send message
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;
    addMessage('user', text);
    inputEl.value = '';

    const config = ROLE_CONFIG[currentRole] || ROLE_CONFIG.generator;
    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          problem: text,
          contest_type: 'MCM/ICM',
          problem_type: 'A',
        }),
      });
      const data = await res.json();
      if (data.content) addMessage('teammate', data.content);
      else addMessage('teammate', '抱歉，生成失败：' + (data.error || '未知错误'));
    } catch(e) {
      addMessage('teammate', '网络错误，请检查连接后重试');
    }
  }

  document.getElementById('teammate-send').addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  // ---- Voice Input ----
  const micBtn = document.getElementById('teammate-mic-btn');
  // Show mic only on mobile
  if (window.innerWidth <= 768) micBtn.hidden = false;

  let recognition = null;
  if ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'zh-CN';

    let silenceTimer;
    recognition.onresult = (e) => {
      let transcript = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        transcript += e.results[i][0].transcript;
      }
      inputEl.value = transcript;
      clearTimeout(silenceTimer);
      silenceTimer = setTimeout(() => {
        if (transcript.trim()) sendMessage();
        recognition.stop();
        micBtn.classList.remove('recording');
      }, 2000);
    };
    recognition.onerror = () => {
      micBtn.classList.remove('recording');
      micBtn.disabled = true;
      micBtn.title = '麦克风权限未开放';
    };
    recognition.onend = () => micBtn.classList.remove('recording');
  } else {
    micBtn.style.display = 'none';
  }

  micBtn.addEventListener('click', () => {
    if (!recognition) return;
    if (micBtn.classList.contains('recording')) {
      recognition.stop();
      micBtn.classList.remove('recording');
    } else {
      try {
        recognition.start();
        micBtn.classList.add('recording');
      } catch(e) {}
    }
  });

  // Expose to global scope
  window.Teammate = { updateRole, addMessage, fetchHint, open, close };
  window._teammateCurrentRole = () => currentRole;
})();
```

- [ ] **Step 4: Wire tab switching to teammate role updates**

In `static/js/app.js`, in the tab switch handler, add:
```javascript
if (window.Teammate) {
  window.Teammate.updateRole(tabName);
  window.Teammate.fetchHint({ tab: tabName, last_action: 'tab_switch', problem_type: document.getElementById('problem-type')?.value || '' });
}
```

- [ ] **Step 5: Wire generation lifecycle to teammate hints**

In `static/js/generator.js`, after stream completes:
```javascript
if (window.Teammate) {
  window.Teammate.fetchHint({
    tab: 'generator',
    last_action: 'generation_complete',
    problem_type: document.getElementById('problem-type')?.value || '',
    problem_text: document.getElementById('problem')?.value || '',
  });
}
```

In generator, when problem text is filled (from Problems tab):
```javascript
if (window.Teammate) {
  window.Teammate.fetchHint({
    tab: 'generator',
    last_action: 'problem_filled',
    problem_type: document.getElementById('problem-type')?.value || '',
    problem_text: document.getElementById('problem')?.value || '',
  });
}
```

- [ ] **Step 6: Commit**

```bash
git add static/js/ai-teammate.js templates/index.html static/style.css static/js/app.js static/js/generator.js
git commit -m "feat: add AI teammate panel with role switching and voice input"
```

---

### Task 7: Stage Progress Cards + Workflow Step Bar

**Files:**
- Modify: `static/js/generator.js` (stage progress card logic)
- Modify: `static/js/paper.js` (ditto for paper generation)
- Modify: `static/style.css` (progress card + step bar styles)
- Modify: `src/routes/generator_routes.py` (add [STAGE:xxx] markers to SSE)
- Modify: `src/routes/paper_routes.py` (add [STAGE:xxx] markers)

- [ ] **Step 1: Add stage markers to generator SSE**

In `src/routes/generator_routes.py`, in the `generate()` function, add:
```python
stages = [
    ("analyze", "分析题目类型"),
    ("match_models", "匹配合适模型"),
    ("build_framework", "构建论文框架"),
    ("write_assumptions", "撰写假设与符号说明"),
    ("generate_code", "生成 Python 代码"),
    ("sensitivity", "生成敏感性分析"),
]
for stage_key, stage_name in stages:
    yield f"data: [STAGE:{stage_name}]\n\n"

# Then proceed with normal content streaming...
```

Similarly for paper generation with paper-specific stages.

- [ ] **Step 2: Create progress card UI in generator.js**

```javascript
function createProgressCard() {
  const card = document.createElement('div');
  card.className = 'progress-card';
  card.id = 'gen-progress-card';
  card.innerHTML = `
    <div class="progress-header">
      <span class="progress-title">生成进度</span>
      <button class="progress-toggle" onclick="this.parentElement.nextElementSibling.classList.toggle('collapsed')">收起</button>
    </div>
    <div class="progress-stages" id="gen-stages"></div>
  `;
  resultContent.prepend(card);
  _progressStartTimes = {};
}

const STAGE_ICONS = {
  '分析题目类型': '🔍',
  '匹配合适模型': '📚',
  '构建论文框架': '📐',
  '撰写假设与符号说明': '✍️',
  '生成 Python 代码': '💻',
  '生成敏感性分析': '📊',
};

function updateStage(stageName, status) {
  const stagesEl = document.getElementById('gen-stages');
  if (!stagesEl) return;
  const icon = STAGE_ICONS[stageName] || '⟳';

  let row = stagesEl.querySelector(`[data-stage="${stageName}"]`);
  if (!row) {
    row = document.createElement('div');
    row.className = 'progress-stage';
    row.dataset.stage = stageName;
    stagesEl.appendChild(row);
  }

  if (status === 'in_progress') {
    row.className = 'progress-stage in-progress';
    row.innerHTML = `<span class="stage-icon">${icon}</span> ${stageName} <span class="stage-spinner"></span>`;
  } else if (status === 'done') {
    row.className = 'progress-stage done';
    row.innerHTML = `<span class="stage-icon">${icon}</span> ${stageName} <span class="stage-check">✓</span>`;
  }
}
```

During SSE streaming, parse `[STAGE:xxx]`:
```javascript
// In SSE reader callback:
if (line.startsWith('[STAGE:')) {
  const stageName = line.replace('[STAGE:', '').replace(']', '');
  // Mark previous stage as done
  const prev = document.querySelector('.progress-stage.in-progress');
  if (prev) updateStage(prev.dataset.stage, 'done');
  updateStage(stageName, 'in_progress');
  continue;
}
```

- [ ] **Step 3: Add progress card CSS**

```css
.progress-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px; margin-bottom: 16px;
}
.progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.progress-toggle { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 12px; }
.progress-stages { display: flex; flex-direction: column; gap: 6px; }
.progress-stages.collapsed { display: none; }
.progress-stage { font-size: 13px; padding: 6px 10px; border-radius: 6px; display: flex; align-items: center; gap: 8px; }
.progress-stage.pending { color: var(--text-secondary); }
.progress-stage.in-progress { background: var(--accent-light); color: var(--accent); font-weight: 500; }
.progress-stage .stage-spinner { width: 14px; height: 14px; border: 2px solid var(--accent); border-top-color: transparent; border-radius: 50%; animation: spin .8s linear infinite; }
.progress-stage.done { color: var(--green); }
.progress-stage .stage-check { margin-left: auto; }
```

- [ ] **Step 4: Add workflow step bar**

```javascript
function createStepBar() {
  const bar = document.createElement('div');
  bar.className = 'step-bar';
  bar.id = 'workflow-step-bar';
  bar.innerHTML = `
    <div class="step-item active" data-step="1"><span class="step-dot">1</span><span class="step-label">选题</span></div>
    <div class="step-arrow">→</div>
    <div class="step-item" data-step="2"><span class="step-dot">2</span><span class="step-label">生成框架</span></div>
    <div class="step-arrow">→</div>
    <div class="step-item" data-step="3"><span class="step-dot">3</span><span class="step-label">完整论文</span></div>
    <div class="step-arrow">→</div>
    <div class="step-item" data-step="4"><span class="step-dot">4</span><span class="step-label">检查优化</span></div>
    <div class="step-arrow">→</div>
    <div class="step-item" data-step="5"><span class="step-dot">5</span><span class="step-label">导出</span></div>
  `;

  bar.querySelectorAll('.step-item').forEach(item => {
    item.addEventListener('click', () => {
      const step = parseInt(item.dataset.step);
      const currentStep = getCurrentStep();
      if (step > currentStep) {
        if (window.Teammate) window.Teammate.addMessage('teammate', '请先完成上一步', []);
      }
    });
  });

  document.getElementById('tab-generator').querySelector('.hero').after(bar);
}

function advanceStep(step) {
  document.querySelectorAll('#workflow-step-bar .step-item').forEach(item => {
    const s = parseInt(item.dataset.step);
    item.classList.remove('active', 'done');
    if (s < step) item.classList.add('done');
    if (s === step) item.classList.add('active');
  });
}
```

Step bar CSS:
```css
.step-bar {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 16px 0; flex-wrap: wrap;
}
.step-item { display: flex; align-items: center; gap: 6px; cursor: default; }
.step-item.done { cursor: pointer; }
.step-dot {
  width: 28px; height: 28px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: 12px;
  font-weight: 600; background: var(--inline-code-bg); color: var(--text-secondary);
  transition: all .3s;
}
.step-item.active .step-dot { background: var(--accent); color: #fff; }
.step-item.done .step-dot { background: var(--green); color: #fff; }
.step-label { font-size: 13px; color: var(--text-secondary); }
.step-item.active .step-label { color: var(--text); font-weight: 500; }
.step-arrow { color: var(--text-secondary); opacity: 0.4; }
@media (max-width: 768px) {
  .step-bar { gap: 4px; }
  .step-label { display: none; }
  .step-arrow { display: none; }
}
```

- [ ] **Step 5: Add interruption recovery**

In generator.js, add draft saving:
```javascript
let _draftInterval = null;
function startDraftSaving(type) {
  _draftInterval = setInterval(() => {
    const content = resultContent?.textContent || '';
    if (content.length > 100) {
      localStorage.setItem(`mma-draft-${type}`, content);
    }
  }, 500);
}
function clearDraft(type) {
  localStorage.removeItem(`mma-draft-${type}`);
  if (_draftInterval) { clearInterval(_draftInterval); _draftInterval = null; }
}
function checkDraft(type) {
  const draft = localStorage.getItem(`mma-draft-${type}`);
  if (draft && window.Teammate) {
    window.Teammate.addMessage('teammate',
      '你有未完成的生成草稿。要继续吗？',
      [{ label: '继续生成', payload: 'resume_draft' }, { label: '放弃草稿', payload: 'discard_draft' }]
    );
  }
}
// Call checkDraft('framework') on Generator tab load
```

- [ ] **Step 6: Commit**

```bash
git add static/js/generator.js static/js/paper.js static/style.css src/routes/generator_routes.py src/routes/paper_routes.py
git commit -m "feat: add stage progress cards, workflow step bar, and draft recovery"
```

---

### Task 8: Empty State Guidance + Integration Polish

**Files:**
- Modify: `templates/index.html` (example problem, starter model cards)
- Modify: `static/js/models.js` (starter recommendations)
- Modify: `static/style.css` (empty state styles)
- Modify: `static/sw.js` (update PWA cache for new JS files)
- Modify: `app.py` (desktop offline detection)

- [ ] **Step 1: Add example problem placeholder to Generator**

In `index.html`, update the problem textarea:
```html
<textarea id="problem" rows="4" placeholder="示例题目（点击下方「试试示例」一键体验）：&#10;&#10;某城市计划建设充电站网络，需要在 50 个候选地点中选择 10 个建站位置，使得所有居民点到最近充电站的距离之和最小。请建立数学模型并求解。"></textarea>
```

Add "Try Example" button next to generate:
```html
<button id="try-example-btn" class="btn-secondary">试试示例</button>
```

- [ ] **Step 2: Add starter model cards in Models tab**

In `models.js`, when models grid is empty (first load before data arrives), show:
```javascript
const STARTER_MODELS = [
  { name: '层次分析法 (AHP)', summary: '多准则决策，适合综合评价类问题', difficulty: '入门' },
  { name: '线性回归', summary: '最基础的数据拟合方法，预测题首选', difficulty: '入门' },
  { name: '蒙特卡洛模拟', summary: '随机模拟，处理不确定性问题的利器', difficulty: '简单' },
];

function renderStarterCards() {
  const grid = document.getElementById('model-grid');
  grid.innerHTML = '<p style="margin-bottom:8px;color:var(--text-secondary)">🎓 推荐入门模型</p>' +
    STARTER_MODELS.map(m => `
      <div class="model-card starter-card" style="border:1px dashed var(--accent);cursor:pointer">
        <h4>${m.name}</h4>
        <p>${m.summary}</p>
        <span class="model-diff-tag">${m.difficulty}</span>
      </div>
    `).join('');
}
```

- [ ] **Step 3: Desktop offline detection**

In `app.py`, add:
```python
import os

@app.context_processor
def inject_offline_mode():
    return {'offline_mode': not os.environ.get('RAILWAY_ENV') and not os.environ.get('DEEPSEEK_API_KEY')}
```

In `index.html`, if offline mode, hide login link:
```html
{% if not offline_mode %}
<a href="/login" id="login-link">登录</a>
{% endif %}
```

- [ ] **Step 4: Update PWA service worker**

In `static/sw.js`, add new JS files to cache list:
```javascript
const CACHE_FILES = [
  '/', '/static/style.css',
  '/static/js/lib.js', '/static/js/auth.js', '/static/js/app.js',
  '/static/js/generator.js', '/static/js/paper.js',
  '/static/js/models.js', '/static/js/problems.js',
  '/static/js/guide.js', '/static/js/ai-teammate.js',
  '/static/manifest.json', '/static/offline.html',
  '/login', '/register',
];
```

- [ ] **Step 5: Full integration test**

```bash
# Start app
cd /Users/wuqqi/math-modeling-assistant
python app.py &
sleep 2

# 1. Home page loads
curl -s http://localhost:8080 | head -20

# 2. Login page loads
curl -s http://localhost:8080/login | head -10

# 3. Register page loads
curl -s http://localhost:8080/register | head -10

# 4. Check auth API
curl -s http://localhost:8080/api/auth/me

# 5. Check context-hint API
curl -s -X POST http://localhost:8080/api/context-hint \
  -H "Content-Type: application/json" \
  -d '{"tab":"generator","problem_type":"A","problem_text":"differential equation optimization"}'

# 6. Check models API
curl -s http://localhost:8080/api/models | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'Models: {d[\"total\"]}')"

# Kill test server
kill %1
```

- [ ] **Step 6: Fix any errors found, then commit**

```bash
git add templates/index.html static/js/models.js static/style.css static/sw.js app.py
git commit -m "feat: add empty state guidance, offline detection, and PWA update"
```

---

### Task 9: End-to-End Testing & Bug Fixing

- [ ] **Step 1: Start app and verify all tabs load**

- [ ] **Step 2: Test register → login → save key → generate flow**

- [ ] **Step 3: Test AI teammate panel (open/close, role switch, send message)**

- [ ] **Step 4: Test voice input on mobile viewport**

- [ ] **Step 5: Test progress cards during generation**

- [ ] **Step 6: Test interruption recovery (abort mid-stream, check draft saved)**

- [ ] **Step 7: Test dark mode + theme flash prevention**

- [ ] **Step 8: Test mobile responsive layout (375px, 768px)**

- [ ] **Step 9: Fix all discovered bugs**

- [ ] **Step 10: Final commit**

---

## Verification Checklist

- [ ] App starts without errors: `python app.py`
- [ ] All 6 tabs load and function correctly
- [ ] Dark mode works without flash
- [ ] Registration flow works (register → auto-login → save key)
- [ ] Login flow works (login → see saved key → logout)
- [ ] AI teammate panel opens/closes, role switches with tabs
- [ ] Context hints appear at correct trigger moments
- [ ] Stage progress cards display during generation
- [ ] Workflow step bar advances correctly
- [ ] Voice input works on mobile (Chrome)
- [ ] Interruption recovery saves/restores drafts
- [ ] Empty states show guidance content
- [ ] PWA offline mode serves cached pages
- [ ] Desktop build detection skips login
- [ ] All existing features preserved (no regression)
