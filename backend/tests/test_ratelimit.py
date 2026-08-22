from app import ratelimit

def test_burst_limited(monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(ratelimit, "_MAX_PER_MINUTE", 3)
    for _ in range(3):
        assert ratelimit.check("s1")[0] is True
    allowed, retry = ratelimit.check("s1")
    assert allowed is False
    assert 55 <= retry <= 61

def test_other_session_unaffected(monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(ratelimit, "_MAX_PER_MINUTE", 3)
    for _ in range(3):
        ratelimit.check("s1")
    assert ratelimit.check("s2")[0] is True

def test_reset_clears():
    ratelimit.reset()
    for _ in range(ratelimit._MAX_PER_MINUTE):
        ratelimit.check("s1")
    ratelimit.reset()
    assert ratelimit.check("s1")[0] is True
