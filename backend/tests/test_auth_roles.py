"""auth.py tests -- mocked login + role checks."""
from app.auth import login, require_role, SESSIONS


def test_login_success():
    r = login("aisha", "parcelpilot")
    assert r is not None
    assert r["role"] == "support_agent"
    assert r["session_id"] in SESSIONS


def test_login_roles_match_config():
    assert login("rohan", "parcelpilot")["role"] == "manager"
    assert login("neha", "parcelpilot")["role"] == "admin"


def test_login_wrong_password():
    assert login("aisha", "nope") is None


def test_login_unknown_user():
    assert login("ghost", "parcelpilot") is None


def test_require_role_allows_manager():
    session = {"username": "rohan", "role": "manager"}
    assert require_role(session, "manager", "admin") is True


def test_require_role_denies_support_agent():
    session = {"username": "aisha", "role": "support_agent"}
    assert require_role(session, "manager", "admin") is False


def test_require_role_denies_anonymous():
    assert require_role(None, "support_agent", "manager", "admin") is False
