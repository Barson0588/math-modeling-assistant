"""Authentication: register, login, logout, key management."""
import uuid
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Blueprint, request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from .db import get_db, init_db

auth_bp = Blueprint('auth', __name__)

# Ensure tables exist once at import time (idempotent)
init_db()

# Encryption for API keys
import base64
import hashlib

ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', '')
if ENCRYPTION_KEY:
    if len(ENCRYPTION_KEY) == 44:
        _fernet = Fernet(ENCRYPTION_KEY.encode())
    else:
        digest = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(digest))
else:
    # Dev fallback: derive key from a static seed (NOT for production!)
    _fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b'mma-dev-key').digest()))
    print("[AUTH] WARNING: Using dev encryption key. Set ENCRYPTION_KEY env var for production.")


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
    try:
        conn.execute("INSERT INTO user (email, password_hash) VALUES (?, ?)",
                     (email, password_hash))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': '该邮箱已注册'}), 409

    user_id = conn.execute("SELECT id FROM user WHERE email = ?", (email,)).fetchone()['id']

    # Auto-login after register
    token = _generate_token()
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn.execute("INSERT INTO session (user_id, token, expires_at) VALUES (?, ?, ?)",
                 (user_id, token, expires))
    conn.commit()
    conn.close()

    resp = jsonify({'status': 'ok', 'email': email})
    resp.set_cookie('mma_session', token, max_age=86400 * 7, httponly=True,
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
    resp.set_cookie('mma_session', token, max_age=86400 * 7, httponly=True,
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
    return jsonify({'api_key': decrypted or '', 'has_key': bool(decrypted)})
