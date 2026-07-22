"""Database layer for MMA — supports both local SQLite and Turso (cloud)."""
import json
import sqlite3
import os
import urllib.request
import urllib.error

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DB_PATH = os.path.join(DB_DIR, 'mma.db')

TURSO_URL = os.environ.get('TURSO_URL', '')
TURSO_AUTH_TOKEN = os.environ.get('TURSO_AUTH_TOKEN', '')

# Convert libsql:// URL to https:// for HTTP pipeline API
_TURSO_HTTP_URL = ''
if TURSO_URL:
    _TURSO_HTTP_URL = TURSO_URL.replace('libsql://', 'https://') + '/v2/pipeline'


# ============================================================
# Turso HTTP wrapper — mimics sqlite3.Connection for drop-in compat
# ============================================================

class _TursoRow:
    """Dict-like + index-based row wrapper."""
    __slots__ = ('_keys', '_vals')

    def __init__(self, keys, vals):
        self._keys = keys
        self._vals = vals

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._vals[self._keys.index(key)]

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


class _TursoCursor:
    """Cursor-like wrapper around Turso HTTP pipeline result."""
    def __init__(self, columns, rows, last_insert_rowid=None):
        self._columns = columns
        self._rows = [_TursoRow(columns, r) for r in rows]
        self._idx = 0
        self.lastrowid = last_insert_rowid

    def fetchone(self):
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return row

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)

    def __bool__(self):
        return len(self._rows) > 0


class _TursoConnection:
    """Wraps Turso HTTP pipeline API to behave like sqlite3.Connection."""
    def __init__(self):
        self.row_factory = None

    def execute(self, sql, params=None):
        if params is None:
            params = []
        elif isinstance(params, tuple):
            params = list(params)

        # Convert params to the format Turso expects
        args = []
        for p in params:
            if isinstance(p, int):
                args.append({'type': 'integer', 'value': str(p)})
            elif isinstance(p, float):
                args.append({'type': 'real', 'value': str(p)})
            elif p is None:
                args.append({'type': 'null', 'value': ''})
            else:
                args.append({'type': 'text', 'value': str(p)})

        body = {
            'requests': [
                {'type': 'execute', 'stmt': {'sql': sql, 'args': args}},
                {'type': 'close'},
            ]
        }

        req = urllib.request.Request(
            _TURSO_HTTP_URL,
            data=json.dumps(body).encode(),
            headers={
                'Authorization': 'Bearer ' + TURSO_AUTH_TOKEN,
                'Content-Type': 'application/json',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise Exception(f'Turso HTTP {e.code}: {e.reason}')

        # Parse pipeline response
        results = data.get('results', [])
        for r in results:
            if r.get('type') == 'execute':
                resp_data = r.get('response', {})
                result = resp_data.get('result', {})
                columns = [c.get('name', '') for c in result.get('columns', [])]
                rows = result.get('rows', [])
                last_id = result.get('last_insert_rowid')
                try:
                    last_id = int(last_id) if last_id else None
                except (ValueError, TypeError):
                    last_id = None
                return _TursoCursor(columns, rows, last_id)

        return _TursoCursor([], [], None)

    def executescript(self, sql):
        stmts = [s.strip() for s in sql.split(';') if s.strip()]
        for stmt in stmts:
            self.execute(stmt)

    def commit(self):
        pass

    def close(self):
        pass


# ============================================================
# Public API
# ============================================================

def get_db():
    if TURSO_URL and TURSO_AUTH_TOKEN:
        return _TursoConnection()
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    if TURSO_URL and TURSO_AUTH_TOKEN:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                encrypted_api_key TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
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
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES user(id),
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
    else:
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
    backend = 'Turso' if (TURSO_URL and TURSO_AUTH_TOKEN) else DB_PATH
    print(f"[DB] Initialized at {backend}")
