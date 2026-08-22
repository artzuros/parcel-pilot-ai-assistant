from app import budget

def test_record_accumulates(monkeypatch):
    monkeypatch.setattr(budget, "_today", lambda: "2026-08-23")
    budget._DAILY.clear()
    assert budget.record("aisha", 1000) == 1000
    assert budget.record("aisha", 500) == 1500
    assert budget.remaining("aisha") == budget._DAILY_CAP - 1500

def test_day_rollover_resets(monkeypatch):
    monkeypatch.setattr(budget, "_today", lambda: "2026-08-23")
    budget._DAILY.clear()
    budget.record("aisha", budget._DAILY_CAP)
    monkeypatch.setattr(budget, "_today", lambda: "2026-08-24")
    assert budget.remaining("aisha") == budget._DAILY_CAP

def test_check_refuses_over_cap(monkeypatch):
    monkeypatch.setattr(budget, "_today", lambda: "2026-08-23")
    budget._DAILY.clear()
    budget.record("aisha", budget._DAILY_CAP - 10)
    assert budget.check("aisha", 50) is False
    assert budget.check("aisha", 5) is True
