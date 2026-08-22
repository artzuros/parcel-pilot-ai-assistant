"""tools.py tests -- registry completeness and dispatch."""
import pytest

from app.auth import login
from app.agent import tools

AISHA = login("aisha", "parcelpilot")

EXPECTED = {"doc_search", "get_account", "get_orders", "get_tickets",
            "sla_deadline", "cancellation_check", "credit_check",
            "classify_severity", "escalate_ticket", "update_ticket",
            "create_followup_task", "propose_credit"}


def test_registry_schema_names():
    names = {t["function"]["name"] for t in tools.TOOLS_SCHEMA}
    assert names == EXPECTED
    for t in tools.TOOLS_SCHEMA:
        assert t["type"] == "function"
        params = t["function"]["parameters"]
        assert params["type"] == "object"
        assert all(p.get("type") for p in params["properties"].values())


def test_dispatch_unknown_tool():
    assert tools.dispatch("nope", AISHA, {})["status"] == "error"


def test_dispatch_doc_search_denied_without_session():
    assert tools.dispatch("doc_search", None, {"query": "pickup"})["status"] == "permission_denied"


def test_dispatch_doc_search_ok():
    r = tools.dispatch("doc_search", AISHA, {"query": "cancellation fee",
                                             "max_results": 2})
    assert r["status"] == "ok"
