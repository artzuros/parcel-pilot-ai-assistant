"""loop.py tests -- tool-call loop mechanics with a stubbed model."""
import pathlib
import tempfile
from types import SimpleNamespace

import pytest

from app.auth import login
from app.data import db
from app.data import seed as seedmod
from app.executors import actions
from app.executors.data_lookup import get_tickets
from app.agent import loop
from app.llm import deepseek

AISHA = login("aisha", "parcelpilot")
ROHAN = login("rohan", "parcelpilot")


@pytest.fixture(scope="module")
def store():
    orig = db.DB_PATH
    db.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "loop.db"
    try:
        db.init_db()
        seedmod.seed_if_empty()
        yield
    finally:
        db.DB_PATH = orig


def make_fake(*responses):
    """Each response: (content_or_None, [tool_call, ...])."""
    responses = [list(r) for r in responses]

    def fake(messages, **kwargs):
        content, calls = responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=calls))])

    return fake


def tc(call_id, name, arguments):
    return SimpleNamespace(id=call_id,
                           function=SimpleNamespace(name=name,
                                                    arguments=arguments))


def test_pause_flow(store, monkeypatch):
    fake = make_fake(
        (None, [tc("c1", "get_tickets", '{"ticket_id": "TKT-501"}')]),
        (None, [tc("c2", "escalate_ticket",
                   '{"ticket_id": "TKT-501", "reason": "high priority"}')]),
        ("Understood - this escalation needs a manager to confirm. Shall I proceed?", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake)
    events = []
    final, pending, msgs = loop.run_turn(AISHA, "Escalate TKT-501 please",
                                         emit=lambda n, p: events.append((n, p)))
    assert final.startswith("Understood")
    assert pending is not None and pending["status"] == "pending"
    names = [n for n, _ in events]
    assert names == ["tool_start", "tool_result",
                     "tool_start", "tool_result", "confirmation_requested"]
    confirmed = events[-1][1]
    assert confirmed["action_id"] == pending["action_id"]
    assert confirmed["requires_role"] == "manager"
    assert any(m["role"] == "system" and "PAUSE" in m["content"] for m in msgs)


def test_malformed_arguments_recovered(store, monkeypatch):
    fake = make_fake(
        (None, [tc("c1", "doc_search", "{not json")]),
        ("The docs are not searchable right now. What exactly are you trying to do?", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake)
    events = []
    final, pending, _ = loop.run_turn(AISHA, "search the docs",
                                      emit=lambda n, p: events.append((n, p)))
    assert "tool_warning" in [n for n, _ in events]
    assert pending is None
    assert final


def test_unknown_tool_survives(store, monkeypatch):
    fake = make_fake(
        (None, [tc("c1", "no_such_tool", "{}")]),
        ("I don't have that capability. What would you like to do instead?", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake)
    final, pending, _ = loop.run_turn(AISHA, "do the thing")
    assert pending is None
    assert final


def test_confirm_flow_via_loop(store, monkeypatch):
    r = actions.escalate_ticket(AISHA, "TKT-501", "urgent")
    assert actions.confirm_action(ROHAN, r["action_id"], approve=True)["status"] == "executed"
    assert get_tickets(AISHA, ticket_id="TKT-501")["tickets"][0]["status"] == "escalated"
    fake = make_fake(
        ("Done - TKT-501 is escalated and the on-call manager will pick it up.", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake)
    final, _, msgs = loop.run_confirmation_continuation(ROHAN, r["action_id"], True)
    assert "escalated" in final
    assert any(m["role"] == "system" and "APPROVED" in m["content"] for m in msgs)
