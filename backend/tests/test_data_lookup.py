"""Data-layer tests: seeding, read tools, and enforcement in the data layer."""
import pathlib
import tempfile

import pytest

from app.data import db
from app.data import seed as seedmod
from app.executors import data_lookup as dl

SUPPORT = {"username": "aisha", "role": "support_agent"}


@pytest.fixture(scope="module")
def store():
    orig = db.DB_PATH
    db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "test.db"
    try:
        db.init_db()
        seedmod.seed_if_empty()
        yield
    finally:
        db.DB_PATH = orig


def test_seed_accounts(store):
    r = dl.get_account(SUPPORT, "ACCT-001")
    assert r["status"] == "ok"
    assert r["account"]["account_name"] == "Northstar Logistics"
    assert r["account"]["premium_support"] is True


def test_get_account_by_name(store):
    r = dl.get_account(SUPPORT, name="northstar")
    assert r["status"] == "ok"
    assert r["account"]["account_id"] == "ACCT-001"


def test_get_account_not_found(store):
    assert dl.get_account(SUPPORT, "ACCT-999")["status"] == "not_found"


def test_orders_filtered_by_account(store):
    r = dl.get_orders(SUPPORT, account_id="ACCT-001")
    assert {o["order_id"] for o in r["orders"]} == {"ORD-1001", "ORD-1002"}


def test_orders_filtered_by_status(store):
    r = dl.get_orders(SUPPORT, account_id="ACCT-001", status="BOOKED")
    assert [o["order_id"] for o in r["orders"]] == ["ORD-1001"]


def test_order_fee_and_fault_flags(store):
    r = dl.get_orders(SUPPORT, order_id="ORD-2002")
    o = r["orders"][0]
    assert o["shipment_fee_inr"] == 2400
    assert o["carrier_fault"] is True
    assert o["customer_fault"] is False


def test_ticket_suspect_confidence_surfaces(store):
    r = dl.get_tickets(SUPPORT, ticket_id="TKT-450")
    t = r["tickets"][0]
    assert t["resolution_confidence"] == "suspect"
    assert t["historical_resolution"]   # resolution text present, flagged as suspect


def test_open_ticket_count(store):
    r = dl.get_tickets(SUPPORT, status="open")
    assert len(r["tickets"]) == 5


def test_seeding_is_idempotent(store):
    assert seedmod.seed_if_empty() is False


def test_unauthenticated_denied(store):
    assert dl.get_account(None, "ACCT-001")["status"] == "permission_denied"
    assert dl.get_orders(None)["status"] == "permission_denied"
    assert dl.get_tickets(None)["status"] == "permission_denied"
