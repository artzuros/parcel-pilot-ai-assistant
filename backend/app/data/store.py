import json, uuid
from datetime import datetime, timedelta

from app.config import REFERENCE_NOW
from app.data.db import get_connection

ACTION_TTL_MINUTES = 10

def create_pending(action_type, session_id, payload, requires_role):
    action_id = f"{action_type}-{uuid.uuid4().hex[:8].upper()}"
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO actions (action_id, session_id, action_type, payload,
                requires_role, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (action_id, session_id, action_type, json.dumps(payload, default=str),
            requires_role,
            REFERENCE_NOW.isoformat(sep=" ", timespec="minutes"),
            (datetime.now() + timedelta(minutes=ACTION_TTL_MINUTES)).isoformat(sep=" ", timespec="minutes")),
        )
        conn.commit()
    finally: conn.close()
    return action_id

def get_pending(action_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM actions WHERE action_id = ?",
                           (action_id,)).fetchone()
        if row is None: return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d
    finally: conn.close()

def is_expired(pending):
    if pending is None or pending.get("status") != "pending":
        return False
    return datetime.now() >= datetime.fromisoformat(pending["expires_at"])

def mark_action(action_id, status):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE actions SET status = ?, executed_at = ? WHERE action_id = ?",
            (status, REFERENCE_NOW.isoformat(sep=" ", timespec="minutes"), action_id))
        conn.commit()
    finally : conn.close()

def log_audit(actor, action_id, event, detail=""):
    conn = get_connection()
    try:
        conn.execute(
        "INSERT INTO audit (actor, action_id, event, detail, at) VALUES (?, ?, ?, ?, ?)",
            (actor, action_id, event, detail,
            REFERENCE_NOW.isoformat(sep=" ", timespec="minutes")))
        conn.commit()
    finally: conn.close()