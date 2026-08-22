"""store.py tests -- pending actions, audit, and TTL expiry."""
import pytest
import pathlib
import tempfile

from app.data import db
from app.data import store
from app.data.db import get_connection


@pytest.fixture(scope="module")
def store_fixture():
    orig = db.DB_PATH
    db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "store-test.db"
    try:
        db.init_db()
        yield
    finally:
        db.DB_PATH = orig


def test_create_and_get_pending(store_fixture):
    aid = store.create_pending("escalate_ticket", "sess-1",
                            {"ticket_id": "TKT-501"}, "manager")
    p = store.get_pending(aid)
    assert p["status"] == "pending"
    assert p["payload"] == {"ticket_id": "TKT-501"}
    assert p["requires_role"] == "manager"


def test_unknown_action_returns_none(store_fixture):
    assert store.get_pending("nope") is None


def test_mark_executed_and_audit(store_fixture):
    aid = store.create_pending("update_ticket", "sess-1",
                               {"ticket_id": "TKT-502"}, "support_agent")
    store.mark_action(aid, "executed")
    store.log_audit("aisha", aid, "action.executed", "TKT-502 priority updated")
    assert store.get_pending(aid)["status"] == "executed"
    conn = get_connection()
    rows = conn.execute("SELECT * FROM audit WHERE action_id = ?", (aid,)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["actor"] == "aisha"
    assert rows[0]["event"] == "action.executed"


def test_ttl_expiry(store_fixture):
    aid = store.create_pending("escalate_ticket", "sess-1", {"ticket_id": "TKT-503"},
                            "manager")
    conn = get_connection()
    conn.execute("UPDATE actions SET expires_at = '2000-01-01 00:00' WHERE action_id = ?",
                (aid,))
    conn.commit()
    conn.close()
    assert store.is_expired(store.get_pending(aid)) is True
    # a fresh pending action is not expired
    aid2 = store.create_pending("escalate_ticket", "sess-1", {"ticket_id": "TKT-503"},
                                "manager")
    assert store.is_expired(store.get_pending(aid2)) is False
