import threading

# Daily token accounting per user, in-memory. Actual usage comes from
# DeepSeek's response `usage` field (no estimation). Wall-clock day boundary
# is infra bookkeeping, same exception class as the action TTL.
_DAILY_CAP = 100_000
_LOCK = threading.Lock()
_DAILY = {}  # username -> (day, total_tokens)

def _today():
    from datetime import date
    return date.today().isoformat()

def record(username, total_tokens):
    """Accumulate real usage; returns the new running total for the day."""
    with _LOCK:
        day = _today()
        d, used = _DAILY.get(username, (day, 0))
        if d != day:
            used = 0
        used += total_tokens
        _DAILY[username] = (day, used)
        return used

def remaining(username):
    with _LOCK:
        d, used = _DAILY.get(username, (_today(), 0))
        return _DAILY_CAP - used if d == _today() else _DAILY_CAP

def check(username, estimated_next_call):
    return remaining(username) >= estimated_next_call
