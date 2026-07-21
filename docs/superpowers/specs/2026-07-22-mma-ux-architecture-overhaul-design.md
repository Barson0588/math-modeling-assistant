# MMA UX & Architecture Overhaul — Design Spec

**Goal:** Transform MMA from a passive tool collection into a guided, proactive experience with AI teammate, progress transparency, user accounts, and maintainable code structure.

**Architecture:** Flask monolith + SQLite persistence + vanilla JS (split files). One new AI teammate panel with three auto-switching roles (Modeler / Writer / Coach). Stage-based progress cards for generation. User registration/login with AES-encrypted API Key storage synced across devices.

**Tech Stack:** Flask + SQLite + vanilla HTML/CSS/JS + flask-login + cryptography + Web Speech API

---

## Module 1: AI Teammate Panel

### UI Layout

- **Floating button:** Bottom-right corner, circular (56px), with role avatar icon + unread red dot badge
- **Desktop panel:** 380px wide slide-in panel from right, 300ms ease-out animation. Does not obscure main content (pushes it left on narrow screens)
- **Panel header:** Current role name + icon (建模手 / 写作手 / 教练), close button
- **Message bubbles:** Teammate messages in light surface-colored bubble (left-aligned), user messages in accent-blue bubble (right-aligned)
- **Input area:** Text input + send button + microphone button (mobile only, via `max-width: 768px`)
- **Typing effect:** Teammate messages render with 30ms/char typewriter effect, skippable on click

### Role Switching (automatic, based on active Tab)

| Tab | Role | Proactive topics |
|-----|------|-----------------|
| Generator | 建模手 (Modeler) | Analyze problem type, recommend model combinations, flag pitfalls |
| Paper | 写作手 (Writer) | Check structure completeness, abstract quality, figure suggestions |
| Models / Problems | 建模手 (Modeler) | Explain model principles, compare model pros/cons |
| Guide / Roles | 教练 (Coach) | Timeline reminders based on current competition day |

### Proactive Suggestions (4 trigger moments)

1. **Problem filled, not generated:** "This looks like a discrete optimization problem. I recommend integer programming + genetic algorithm. Want me to elaborate?" → [Yes] [No]
2. **Generation complete:** "Framework generated. Section 2 might be missing data source justification. Also, want me to verify the references?" → [Edit] [Check References] [Continue]
3. **Inactivity (90s no action):** "Looks like you could use help. Your framework is still missing sensitivity analysis — I can generate the code for that."
4. **Tab switch:** On switching to Models tab, auto-filter recommended models based on problem type in Generator.

### Backend API

- `POST /api/context-hint` — Accepts `{tab, problem_type, problem_text, last_action, idle_seconds}`. Returns `{hint_text, actions: [{label, callback}]}`. 
- Returns in <200ms. Uses keyword matching + template selection, NOT LLM call.
- LLM only invoked when user clicks an action button that requires generation.

### Visual Polish

- Floating button opacity reduces to 0.5 while user scrolls, restores on scroll stop
- Red badge count for unread teammate messages
- Dark mode: teammate bubble uses `--surface`, user bubble uses `--accent`
- Mobile: panel opens as bottom sheet (70vh), not side panel

---

## Module 2: Generation Experience

### Stage Progress Cards

Replace "准备中..." spinner with live stage indicator.

Stages (order varies by generation type):
```
1. Analyzing problem type
2. Matching optimal models
3. Building paper framework
4. Writing assumptions & notation
5. Generating Python code
6. Generating sensitivity analysis
```

**Implementation:** Backend emits `[STAGE:<stage_name>]` tokens in SSE stream. Frontend parses them, renders progress card separately from streaming content.

**Visual states:**
- Completed: green checkmark + elapsed time
- In-progress: blue pulse animation + spinner
- Pending: gray, muted

**Behavior:** Completed stages auto-collapse after 3s. In-progress stage stays visible. Card collapsible via toggle.

### Guided Workflow Step Bar

Visible in Generator and Paper tabs only:

```
●选题 ──→ ○生成框架 ──→ ○完整论文 ──→ ○检查优化 ──→ ○导出
```

- Current step: filled circle with accent color
- Completed steps: green checkmark, clickable to review
- Future steps: gray hollow circle, click shows teammate hint "Complete previous step first"
- Mobile: compressed to row of 5 dots

**Step transitions:**
- Problem filled from Problems tab → auto-advance to step 2
- Framework generated → advance to step 3
- Full paper generated → advance to step 4
- At least one check run → advance to step 5

### Interruption Recovery

- Stream content saved to `localStorage` key `mma-draft-{type}` in real-time (every 500ms debounced)
- On network error / abort: teammate panel shows "Generation interrupted. 60% of content saved. Resume or restart?"
- On page reload: if draft exists, teammate asks "You have an unfinished draft. Continue?"
- Draft cleared on successful completion

---

## Module 3: Voice Input + Mobile + Empty States

### Voice Input

- **API:** Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`), zero dependencies
- **Visibility:** Only on screens ≤768px wide
- **Interaction:** Press mic button → recording starts → real-time transcription in input → release or 2s silence auto-sends
- **Error handling:** Permission denied → button grays out, no error popup, hover tooltip "Microphone permission not granted"
- **Browser support:** Chrome (full), Safari (partial, 15+), Firefox (not supported → button hidden)

### Mobile Adaptations

- AI teammate panel: bottom Sheet (70vh), swipe-down to dismiss
- Step bar: 5-dot indicator instead of text labels
- Teammate messages: collapsed by default, red badge on floating button signals new messages
- Progress card: only shows current + next stage on mobile

### Empty State Guidance

| Scenario | Current | New |
|----------|---------|-----|
| First visit Generator | Empty form | Pre-filled example problem (placeholder style) + "Try Example" button that triggers a demo generation |
| First visit Models | Empty grid | Top row: 3 "Recommended Starter" cards (AHP, Linear Regression, Monte Carlo) |
| First visit Paper analysis | Buttons scattered | Teammate proactively: "Got a paper draft? I can check plagiarism, score it, verify math, and more." |

---

## Module 4: User System & Architecture

### Database (SQLite, file: `data/mma.db`)

```sql
CREATE TABLE user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    encrypted_api_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES user(id),
    contest_type TEXT,
    problem_type TEXT,
    problem_text TEXT,
    result_content TEXT,
    content_type TEXT DEFAULT 'framework',  -- 'framework' | 'paper' | 'ai-report'
    starred INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',  -- JSON array
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES user(id),
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL
);
```

### API Key Storage

- Encrypted with AES-256-GCM using `cryptography` library
- Encryption key from env var `ENCRYPTION_KEY` (32-byte hex, set in Railway secrets)
- Decrypted on login, stored in server-side session, injected into LLM calls
- Key syncs across devices via user account

### Authentication Flow

1. User registers at `/register` (email + password + confirm)
2. Password hashed with `bcrypt` via `werkzeug.security`
3. Login creates session token (UUID4), stored in `session` table with 7-day expiry
4. Session cookie: `mma_session` (httpOnly, Secure, SameSite=Lax)
5. `flask-login` manages `current_user` and `@login_required` decorator

### New Pages

| Route | Template | Description |
|-------|----------|-------------|
| `/login` | `login.html` | Email + password form, "Remember me", link to register |
| `/register` | `register.html` | Email + password + confirm, link to login |
| `/logout` | — | POST only, clears session, redirects to `/` |

### New Dependencies

```
# requirements.txt additions:
flask-login>=0.6.0
cryptography>=41.0.0
```

### JS File Split

```
static/js/
  app.js          # Init, theme, tab switching, keyboard shortcuts (~400 lines)
  auth.js         # Login/register/Key management (~200 lines)
  generator.js    # Generator tab + SSE streaming + progress cards (~600 lines)
  paper.js        # Paper tab + TOC + analysis tools (~800 lines)
  models.js       # Model library + comparison (~400 lines)
  problems.js     # Problem database (~300 lines)
  guide.js        # Guide + timeline + roles (~300 lines)
  ai-teammate.js  # AI teammate panel + voice input (new, ~400 lines)
  lib.js          # Shared: toast, escapeHtml, marked config (~200 lines)
```

Loaded in `index.html` in dependency order. No bundler, no build step.

### Backend File Split

```
app.py             # Flask app factory, config, route registration (~200 lines)
auth.py            # Login/register/logout routes + user model (new, ~200 lines)
routes/
  generator.py     # /api/generate, /api/generate/stream, /api/ai-report (~150 lines)
  paper.py         # /api/generate-paper/*, paper analysis routes (~200 lines)
  models.py        # /api/models (~50 lines)
  problems.py      # /api/problems (~50 lines)
  guide.py         # /api/guide, /api/roles (~50 lines)
  context_hint.py  # /api/context-hint (new, ~80 lines)
  history.py       # /api/history CRUD (new, ~100 lines)
db.py              # SQLite connection, init schema, query helpers (new, ~120 lines)
```

### Migration Path

- Existing `localStorage` history: on first login, frontend offers to import local history into server account
- Existing `localStorage` API Key: migrated to server on first successful verification after login
- Desktop builds: continue using env var `DEEPSEEK_API_KEY` path; user system is optional (skip login for offline use)

---

## Global Constraints

- Zero new frontend frameworks — vanilla HTML/CSS/JS only
- Zero build steps — no bundler, no transpiler, no npm
- All existing features preserved — no regression on Generator, Paper, Models, Problems, Guide, Roles
- PWA continues working — service worker updated for new routes
- Railway single-container deployment unchanged
- Desktop build (PyInstaller) still works — detect offline mode, skip auth
- SQLite only — no PostgreSQL or external DB dependency
- Voice input uses Web Speech API only — no third-party speech service
- All teammate suggestions use keyword matching (not LLM) for <200ms response
- Chinese-first UI language, English for MCM/ICM paper content
