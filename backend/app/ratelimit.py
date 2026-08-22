import time

# In-memory sliding window per session (matches SESSIONS/CHATS — in-memory).
# Per-user/per-IP limits are the production extension.
_MAX_PER_MINUTE = 15
_WINDOW_SECONDS = 60
_HITS = {}  # session_id -> [timestamps]

def check(session_id):
    """Return (allowed, retry_after_seconds)."""
    now = time.time()
    hits = _HITS.setdefault(session_id, [])
    hits[:] = [t for t in hits if now - t < _WINDOW_SECONDS]
    if len(hits) >= _MAX_PER_MINUTE:
        return False, int(hits[0] + _WINDOW_SECONDS - now) + 1
    hits.append(now)
    return True, 0

def reset(session_id=None):
    if session_id is None:
        _HITS.clear()
    else:
        _HITS.pop(session_id, None)
