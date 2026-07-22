"""Database layer for MMA — supports both local SQLite and Turso (cloud)."""
import sqlite3
import os

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DB_PATH = os.path.join(DB_DIR, 'mma.db')

TURSO_URL = os.environ.get('TURSO_URL', '')
TURSO_AUTH_TOKEN = os.environ.get('TURSO_AUTH_TOKEN', '')


# ============================================================
# Turso wrapper — mimics sqlite3.Connection for drop-in compat
# ============================================================

class _TursoRow:
    """Dict-like row wrapper around libsql-client Row."""
    __slots__ = ('_d', '_keys', '_vals')

    def __init__(self, row):
        self._d = row.asdict()
        self._keys = list(self._d.keys())
        self._vals = list(self._d.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._d[key]

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


class _TursoCursor:
    """Cursor-like wrapper around a libsql-client ResultSet."""
    def __init__(self, result_set):
        self._result = result_set
        self._idx = 0
        self._rows = [_TursoRow(r) for r in (result_set.rows or [])]

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
    """Wraps a libsql-client sync client to behave like sqlite3.Connection."""
    def __init__(self, client):
        self._client = client
        self.row_factory = None  # ignored; rows always behave like sqlite3.Row

    def execute(self, sql, params=None):
        if params is None:
            params = []
        elif isinstance(params, tuple):
            params = list(params)
        result = self._client.execute(sql, params)
        return _TursoCursor(result)

    def executescript(self, sql):
        stmts = [s.strip() for s in sql.split(';') if s.strip()]
        for stmt in stmts:
            self._client.execute(stmt)

    def commit(self):
        pass

    def close(self):
        pass  # shared HTTP client, don't close per-request


# ============================================================
# Public API (same as before)
# ============================================================

_turso_client = None


def _get_turso_client():
    global _turso_client
    if _turso_client is None:
        from libsql_client import create_client_sync
        _turso_client = create_client_sync(url=TURSO_URL, auth_token=TURSO_AUTH_TOKEN)
    return _turso_client


def get_db():
    if TURSO_URL and TURSO_AUTH_TOKEN:
        return _TursoConnection(_get_turso_client())
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
        # Turso: each statement auto-commits, no need for explicit commit
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
