"""Trap suite for policy_core — every number the assessment is testing.

Run: cd backend && python -m pytest tests/ -v
(Requires data/seed/*.json — run docs-processing/build_seed.py first.)
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.config import REFERENCE_NOW
from app.executors import policy_core as pc

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"
NOW = REFERENCE_NOW  # 2026-08-16 11:00 Asia/Kolkata (a Sunday)


def _load(name, key):
    path = SEED_DIR / f"{name}.json"
    if not path.exists():
        pytest.skip(f"Seed data missing — run docs-processing/build_seed.py first ({path})")
    return {r[key]: r for r in json.loads(path.read_text(encoding="utf-8"))}


@pytest.fixture(scope="module")
def accounts():
    return _load("accounts", "account_id")


@pytest.fixture(scope="module")
def orders():
    return _load("orders", "order_id")


@pytest.fixture(scope="module")
def tickets():
    return _load("tickets", "ticket_id")


def order(**overrides):
    base = dict(
        account_id="ACCT-003", carrier="RoadRunner", status="BOOKED",
        booked_at="2026-08-16 10:25",
        pickup_window_start="2026-08-16 07:00", pickup_window_end="2026-08-16 08:00",
        pickup_actual_at=None, shipment_fee_inr=1200,
        carrier_fault=True, customer_fault=False, cancellation_requested_at=None,
        notes=None,
    )
    base.update(overrides)
    return base


# --- SLA: defaults (policy v3) ---------------------------------------------------
def test_sla_v3_defaults():
    assert pc.sla_for(None, "enterprise", "P1")["value"] == 30
    assert pc.sla_for(None, "enterprise", "P1")["unit"] == "minute"
    assert pc.sla_for(None, "enterprise", "P2")["value"] == 2
    assert pc.sla_for(None, "enterprise", "P3")["value"] == 1
    assert pc.sla_for(None, "growth", "P1")["unit"] == "business_hour"
    assert pc.sla_for(None, "growth", "P2")["value"] == 4
    assert pc.sla_for(None, "growth", "P3")["value"] == 2
    assert pc.sla_for(None, "standard", "P1")["value"] == 4
    assert pc.sla_for(None, "standard", "P2")["value"] == 1
    assert pc.sla_for(None, "standard", "P3")["value"] == 2


def test_sla_northstar_override(accounts):
    for sev, value in (("P1", 15), ("P2", 1), ("P3", 8)):
        sla = pc.sla_for("ACCT-001", accounts["ACCT-001"]["plan"], sev)
        assert sla["value"] == value
        assert sla["source"] == "agreement"


def test_sla_northstar_p1_24x7():
    sla = pc.sla_for("ACCT-001", "enterprise", "P1")
    assert sla["coverage"] == "24x7"
    assert pc.has_weekend_coverage("ACCT-001", "P1") is True


def test_sla_lumenworks_override(accounts):
    sla = pc.sla_for("ACCT-002", accounts["ACCT-002"]["plan"], "P1")
    assert sla["value"] == 2 and sla["unit"] == "business_hour"
    assert sla["source"] == "agreement"
    assert pc.has_weekend_coverage("ACCT-002", "P1") is False


def test_sla_never_uses_v2():
    # v2 said Enterprise P1 = 1 hour; current policy v3 = 30 minutes.
    sla = pc.sla_for(None, "enterprise", "P1")
    assert sla["value"] == 30 and sla["source"] == "policy_v3"
    assert sla["deprecated_v2_value"]["value"] == 1  # history only


def test_sla_deadline_wall_clock():
    sla = pc.sla_for("ACCT-001", "enterprise", "P1")  # 15 minutes, 24x7
    assert pc.sla_deadline(sla, datetime(2026, 8, 16, 10, 30)) == datetime(2026, 8, 16, 10, 45)


def test_sla_deadline_business_hours():
    # LumenWorks P2 = 4 business hours from Tue 16:00 -> Wed 11:00.
    sla = pc.sla_for("ACCT-002", "growth", "P2")
    assert pc.sla_deadline(sla, datetime(2026, 8, 18, 16, 0)) == datetime(2026, 8, 19, 11, 0)


def test_sla_deadline_business_days_skips_weekend():
    # Standard P3 = 2 business days from Saturday -> Tuesday 18:00.
    sla = pc.sla_for(None, "standard", "P3")
    assert pc.sla_deadline(sla, datetime(2026, 8, 15, 9, 0)) == datetime(2026, 8, 18, 18, 0)


# --- SLA breaches at snapshot ----------------------------------------------------
def test_tkt501_p1_breached(accounts, tickets):
    t = tickets["TKT-501"]
    sla = pc.sla_for(t["account_id"], accounts[t["account_id"]]["plan"], "P1")
    deadline = pc.sla_deadline(sla, pc.parse_dt(t["created_at"]))
    last = pc.parse_dt(t["last_customer_message_at"])
    assert deadline == datetime(2026, 8, 16, 10, 45)
    assert last > deadline  # breached


def test_tkt505_p1_breached(accounts, tickets):
    t = tickets["TKT-505"]
    sla = pc.sla_for(t["account_id"], accounts[t["account_id"]]["plan"], "P1")
    deadline = pc.sla_deadline(sla, pc.parse_dt(t["created_at"]))
    assert deadline == datetime(2026, 8, 16, 9, 0)
    assert pc.parse_dt(t["last_customer_message_at"]) > deadline  # breached


def test_tkt504_p2_not_breached(accounts, tickets):
    t = tickets["TKT-504"]
    sla = pc.sla_for(t["account_id"], accounts[t["account_id"]]["plan"], "P2")
    deadline = pc.sla_deadline(sla, pc.parse_dt(t["created_at"]))
    assert deadline == datetime(2026, 8, 16, 11, 50)
    assert pc.parse_dt(t["last_customer_message_at"]) <= deadline


# --- Severity classification -------------------------------------------------------
def test_classify_severity(tickets):
    assert pc.classify_severity(tickets["TKT-501"]["subject"])["severity"] == "P1"
    assert pc.classify_severity(tickets["TKT-505"]["description"])["severity"] == "P1"
    assert pc.classify_severity(tickets["TKT-502"]["subject"])["severity"] == "P2"
    assert pc.classify_severity(tickets["TKT-504"]["subject"])["severity"] == "P2"
    assert pc.classify_severity(tickets["TKT-503"]["subject"])["severity"] == "P3"


# --- Cancellation matrix ------------------------------------------------------------
def test_cancel_ord1001_northstar_waived(orders, accounts):
    r = pc.check_cancellation(orders["ORD-1001"], accounts["ACCT-001"])
    assert r["allowed"] is True and r["fee_inr"] == 0
    assert r["source"] == "agreement"


def test_cancel_ord1001_ki211_caveat(orders, accounts):
    r = pc.check_cancellation(orders["ORD-1001"], accounts["ACCT-001"])
    assert any("KI-211" in c for c in r["caveats"])


def test_cancel_ord2001_fee_after_30min(orders, accounts):
    r = pc.check_cancellation(orders["ORD-2001"], accounts["ACCT-002"])
    assert r["allowed"] is True and r["fee_inr"] == 250
    assert r["source"] == "sop_v4"


def test_cancel_ord3001_free_within_30min(orders, accounts):
    r = pc.check_cancellation(orders["ORD-3001"], accounts["ACCT-003"])
    assert r["allowed"] is True and r["fee_inr"] == 0


def test_cancel_ord1002_picked_up_return_to_origin(orders, accounts):
    r = pc.check_cancellation(orders["ORD-1002"], accounts["ACCT-001"])
    assert r["allowed"] is False and "return-to-origin" in r["reason"]


def test_cancel_ord4001_delivered(orders, accounts):
    r = pc.check_cancellation(orders["ORD-4001"], accounts["ACCT-004"])
    assert r["allowed"] is False


# --- Failed-pickup credits ------------------------------------------------------------
def test_credit_ord2002_lumenworks_fixed_300(orders, accounts):
    r = pc.calculate_credit_eligibility(orders["ORD-2002"], accounts["ACCT-002"])
    assert r["eligible"] is True
    assert r["amount_inr"] == 300  # NOT min(500, 10% of 2400) = 240
    assert r["source"] == "agreement"
    assert r["approval_required"] is False


def test_credit_default_math():
    r = pc.calculate_credit_eligibility(order(), {"account_id": "ACCT-003"})
    assert r["eligible"] is True and r["amount_inr"] == 120  # min(500, 10% of 1200)
    r = pc.calculate_credit_eligibility(order(shipment_fee_inr=6000), {"account_id": "ACCT-003"})
    assert r["amount_inr"] == 500  # capped
    r = pc.calculate_credit_eligibility(order(shipment_fee_inr=20000), {"account_id": "ACCT-003"})
    assert r["amount_inr"] == 500              # 10% = 2000, but capped at 500
    assert r["approval_required"] is False     # default cap keeps credits under the 1,000 approval line


def test_credit_approval_required_via_agreement(monkeypatch):
    # Only an agreement can raise a credit above INR 1,000 -> manager approval.
    overrides = dict(pc.CREDIT_OVERRIDES)
    overrides["ACCT-999"] = {"threshold_hours": 2, "amount_inr": 1500}
    monkeypatch.setattr(pc, "CREDIT_OVERRIDES", overrides)
    r = pc.calculate_credit_eligibility(
        order(account_id="ACCT-999"), {"account_id": "ACCT-999"})
    assert r["eligible"] is True
    assert r["amount_inr"] == 1500
    assert r["approval_required"] is True


def test_credit_threshold_not_met():
    r = pc.calculate_credit_eligibility(
        order(pickup_window_end="2026-08-16 10:00"), {"account_id": "ACCT-003"})
    assert r["eligible"] is False


def test_credit_no_promise_when_fault_unknown():
    r = pc.calculate_credit_eligibility(order(carrier_fault=None), {"account_id": "ACCT-003"})
    assert r["eligible"] is False
    assert "promise" in r["reason"].lower()       # never promise a credit
    assert "verification" in r["reason"].lower()


def test_credit_customer_fault_excluded():
    r = pc.calculate_credit_eligibility(order(customer_fault=True), {"account_id": "ACCT-003"})
    assert r["eligible"] is False


def test_credit_northstar_monthly_cap_reported(accounts):
    r = pc.calculate_credit_eligibility(
        order(account_id="ACCT-001", carrier_fault=True), accounts["ACCT-001"])
    assert r["eligible"] is True
    assert r["monthly_cap_inr"] == 5000



def test_credit_no_cap_for_others(orders, accounts):
    r = pc.calculate_credit_eligibility(orders["ORD-2002"], accounts["ACCT-002"])
    assert "monthly_cap_inr" not in r


# --- Reference time sanity ------------------------------------------------------------
def test_reference_now_is_sunday():
    assert NOW.weekday() == 6  # Sunday — weekend-support logic matters
