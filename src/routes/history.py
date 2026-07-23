"""History CRUD API routes."""
import json
from flask import Blueprint, request, jsonify, g
from src.auth import login_required, get_current_user
from src.db import get_db

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

    return jsonify({'history': [dict(row) for row in rows]})


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
    return jsonify(dict(row if row else {}))


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
