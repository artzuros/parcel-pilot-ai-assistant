"""calc.py tests -- policy wrappers return the deterministic answers."""
import pathlib
import tempfile

import pytest

from app.auth import login
from app.data import db
from app.data import seed as seedmod
from app.executors import calc

SUPPORT = login("aisha", "parcelpilot")


@pytest.fixture(scope="module")
def store():
    orig = db.DB_PATH
    db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "calc.db"
    try:
        db.init_db()
        seedmod.seed_if_empty()
        yield
    finally:
        db.DB_PATH = orig


def test_sla_tkt501_northstar_agreement_overrides(store):
    r = calc.sla_deadline_tool(SUPPORT, "TKT-501")
    assert r["status"] == "ok"
    assert r["severity"] == "P1"
    assert r["source"] == "agreement"
    assert r["sla_value"] == "15 minute"
    assert r["deadline"] == "2026-08-16 10:45"
    assert "DEPRECATED" in r["note_v2"]   # v2 (1 hour) is surfaced, not applied


def test_sla_tool_other_ticket_ok(store):
    r = calc.sla_deadline_tool(SUPPORT, "TKT-505")
    assert r["status"] == "ok"
    assert r["deadline"] > r["start"]    # string compare is fine on this ISO format


def test_classify_severity_bulk_upload(store):
    r = calc.classify_severity_tool(SUPPORT, "bulk upload rows failing again")
    assert r["severity"] == "P2"
    assert "bulk upload" in r["signals"]


def test_cancel_ord1001_northstar_waiver(store):
    r = calc.cancellation_check_tool(SUPPORT, "ORD-1001")
    assert r["status"] == "ok"
    assert r["result"]["allowed"] is True
    assert r["result"]["fee_inr"] == 0
    assert r["result"]["source"] == "agreement"


def test_cancel_ord2001_standard_fee(store):
    r = calc.cancellation_check_tool(SUPPORT, "ORD-2001")
    assert r["result"]["fee_inr"] == 250


def test_cancel_ord3001_free_within_window(store):
    r = calc.cancellation_check_tool(SUPPORT, "ORD-3001")
    assert r["status"] == "ok"
    assert r["result"]["allowed"] is True
    assert r["result"]["fee_inr"] == 0
    assert "caveats" in r["result"]


def test_credit_ord2002_lumenworks_fixed(store):
    r = calc.credit_check_tool(SUPPORT, "ORD-2002")
    assert r["status"] == "ok"
    assert r["result"]["eligible"] is True
    assert r["result"]["amount_inr"] == 300
    assert r["result"]["source"] == "agreement"
