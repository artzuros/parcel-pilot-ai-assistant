from app.config import USERS
import uuid

SESSIONS = {} # session_id -> {username, role, name}

def login(username, password):
    user = USERS.get(username)
    if user is None or user.get("password") != password:
        return None
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = {
        "session_id": session_id,
        "username": username,
        "role": user.get("role"),
        "name": user.get("name") or username,
    }
    return {
        "session_id": session_id,
        "username": username,
        "role": user.get("role"),
        "name": user.get("name") or username,
    }

def get_session(session_id):
    return SESSIONS.get(session_id)

def require_role(session, *roles):
    return session is not None and session.get("role") in roles
