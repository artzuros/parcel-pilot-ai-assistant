"""Confirmation-gate tests: nothing state-changing happens without an
explicit confirm_action, and role checks gate the confirm itself."""
import pathlib
import tempfile

import pytest

from app.auth import login
from app.data import db
from app.data import seed as seedmod
from app.data import store
from app.executors import actions
from app.executors import policy_core as pc
from app.executors.data_lookup import get_tickets

AISHA = login("aisha", "parcelpilot")
ROHAN = login("rohan", "parcelpilot")


@pytest.fixture(scope="module")
def gate():
    orig = db.DB_PATH
    db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "gate.db"
    try:
        db.init_db()
        seedmod.seed_if_empty()
        yield
    finally:
        db.DB_PATH = orig


def test_escalate_requires_manager_confirm(gate):
    r = actions.escalate_ticket(AISHA, "TKT-501", "Customer escalated on phone")
    assert r["status"] == "pending"
    assert r["requires_role"] == "manager"
    # support agent may not confirm an escalation
    assert actions.confirm_action(AISHA, r["action_id"])["status"] == "permission_denied"
    # manager confirms -> executed + ticket escalated
    assert actions.confirm_action(ROHAN, r["action_id"])["status"] == "executed"
    t = get_tickets(AISHA, ticket_id="TKT-501")["tickets"][0]
    assert t["status"] == "escalated"


def test_reject_leaves_ticket_untouched(gate):
    r = actions.escalate_ticket(AISHA, "TKT-502", "Test escalation")
    assert actions.confirm_action(ROHAN, r["action_id"], approve=False)["status"] == "rejected"
    t = get_tickets(AISHA, ticket_id="TKT-502")["tickets"][0]
    assert t["status"] != "escalated"
    # a second confirm on the same action is a no-op
    assert actions.confirm_action(ROHAN, r["action_id"])["status"] == "already_handled"


def test_update_ticket_status_via_gate(gate):
    r = actions.update_ticket(AISHA, "TKT-503", "status", "resolved")
    assert r["status"] == "pending"
    assert actions.confirm_action(AISHA, r["action_id"])["status"] == "executed"
    assert get_tickets(AISHA, ticket_id="TKT-503")["tickets"][0]["status"] == "resolved"


def test_update_ticket_field_whitelist(gate):
    r = actions.update_ticket(AISHA, "TKT-503", "priority", "P1")
    assert r["status"] == "error"


def test_followup_task_after_confirm(gate):
    r = actions.create_followup_task(AISHA, "TKT-504",
                                     "Verify webhook with SwiftShip",
                                     due_at="2026-08-17 10:00")
    assert r["status"] == "pending"
    assert actions.confirm_action(AISHA, r["action_id"])["status"] == "executed"
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM tasks").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["ticket_id"] == "TKT-504"
    assert rows[0]["description"] == "Verify webhook with SwiftShip"
    assert rows[0]["due_at"] == "2026-08-17 10:00"


def test_expired_action_cannot_execute(gate):
    r = actions.escalate_ticket(AISHA, "TKT-505", "")
    conn = db.get_connection()
    conn.execute("UPDATE actions SET expires_at = '2000-01-01 00:00' WHERE action_id = ?",
                 (r["action_id"],))
    conn.commit()
    conn.close()
    res = actions.confirm_action(ROHAN, r["action_id"])
    assert res["status"] == "expired"
    assert store.get_pending(r["action_id"])["status"] == "expired"
    assert get_tickets(AISHA, ticket_id="TKT-505")["tickets"][0]["status"] != "escalated"


def test_credit_under_threshold_confirmable_by_support(gate):
    # ORD-2002 -> LumenWorks fixed INR 300, below the INR 1,000 manager line
    r = actions.propose_credit(AISHA, "ORD-2002")
    assert r["status"] == "pending"
    assert r["amount_inr"] == 300
    assert r["requires_role"] == "support_agent"
    assert actions.confirm_action(AISHA, r["action_id"])["status"] == "executed"
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM credits WHERE order_id = 'ORD-2002'").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0]["amount_inr"] == 300


def test_credit_over_threshold_requires_manager(gate, monkeypatch):
    monkeypatch.setitem(pc.CREDIT_OVERRIDES, "ACCT-002",
                        {"threshold_hours": 0, "amount_inr": 1500})
    r = actions.propose_credit(AISHA, "ORD-2002")
    assert r["status"] == "pending"
    assert r["amount_inr"] == 1500
    assert r["requires_role"] == "manager"
    assert actions.confirm_action(AISHA, r["action_id"])["status"] == "permission_denied"
    assert actions.confirm_action(ROHAN, r["action_id"])["status"] == "executed"
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM credits WHERE order_id = 'ORD-2002'").fetchall()
    conn.close()
    assert len(rows) == 2    # one from each credit test; both on record


def test_credit_monthly_cap_enforced(gate):
    # Make ORD-1001 (ACCT-001 / Northstar) credit-eligible: carrier fault +
    # pickup 2.5h past the window end -> SOP v4 default = min(500, 10% of 4200).
    conn = db.get_connection()
    conn.execute("UPDATE orders SET carrier_fault = 1, customer_fault = 0, "
                 "pickup_actual_at = '2026-08-16 14:00' WHERE order_id = 'ORD-1001'")
    conn.commit()
    r = actions.propose_credit(AISHA, "ORD-1001")
    assert r["status"] == "pending" and r["amount_inr"] == 420

    # INR 4,800 already issued for the account this reference month (2026-08):
    # 4,800 + 420 > the INR 5,000 Northstar monthly cap -> no credit proposed.
    conn.execute("""INSERT INTO credits (credit_id, order_id, amount_inr, status,
                    issued_at, issued_by)
                    VALUES ('CR-CAPTEST', 'ORD-1001', 4800, 'issued',
                            '2026-08-16 09:00', 'test')""")
    conn.commit()
    conn.close()

    r2 = actions.propose_credit(AISHA, "ORD-1001")
    assert r2["status"] == "cap_exceeded"
    assert r2["monthly_cap_inr"] == 5000
    assert r2["issued_this_month_inr"] == 4800
    assert r2["requested_inr"] == 420


def test_confirm_unknown_action(gate):
    assert actions.confirm_action(ROHAN, "escalate_ticket-XXXX")["status"] == "not_found"
