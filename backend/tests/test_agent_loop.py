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
        ("The escalation has been submitted and awaits manager approval.", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake)
    events = []
    final, pending, msgs = loop.run_turn(AISHA, "Escalate TKT-501 please",
                                         emit=lambda n, p: events.append((n, p)))
    # Routing contract: no pause, no card — the model replies naturally and
    # the action waits in the pending store for the manager.
    assert "submitted" in final.lower()
    assert pending is not None
    assert pending.get("status") == "pending"
    assert pending.get("requires_role") == "manager"
    assert not any(n == "confirmation_requested" for n, _ in events)
    # the tool response for the pending call must exist (1 call -> 1 response)
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c2"
               for m in msgs)




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

def test_routing_rewrites_proposers_history(store, monkeypatch):
    fake = make_fake(
        (None, [tc("c1", "get_tickets", '{"ticket_id": "TKT-501"}')]),
        (None, [tc("c2", "escalate_ticket",
                   '{"ticket_id": "TKT-501", "reason": "urgent"}')]),
        ("The escalation has been submitted and awaits manager approval.", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake)
    final, pending, msgs = loop.run_turn(AISHA, "Escalate TKT-501 please")
    assert pending and pending.get("action_id")
    loop.CHATS[AISHA["session_id"]] = msgs          # simulate main.py
    assert loop.PENDING_TC[pending["action_id"]]["session_id"] == AISHA["session_id"]

    # Rohan (manager) approves from his own session — aisha's stored
    # history must now reflect the executed outcome.
    fake2 = make_fake(
        ("TKT-501 has been escalated. The on-call manager will pick it up.", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake2)
    final2, _, _ = loop.run_confirmation_continuation(
        ROHAN, pending["action_id"], True)
    assert "escalated" in final2
    stored = loop.CHATS[AISHA["session_id"]]
    tool_msgs = [m for m in stored if m.get("role") == "tool"]
    assert any('"executed"' in m.get("content", "") for m in tool_msgs)
    assert pending["action_id"] not in loop.PENDING_TC   # registry consumed

    loop.CHATS.clear()   # don't leak state into other tests

def test_pending_approvals_tool(store, monkeypatch):
    actions.escalate_ticket(AISHA, "TKT-501", "urgent")
    fake = make_fake(
        (None, [tc("c1", "pending_approvals", "{}")]),
        ("You have 1 approval awaiting your role: escalate TKT-501.", []),
    )
    monkeypatch.setattr(deepseek, "chat", fake)
    events = []
    final, _, _ = loop.run_turn(ROHAN, "any approvals for me?",
                                emit=lambda n, p: events.append((n, p)))
    assert any(n == "tool_start" and p.get("tool") == "pending_approvals"
               for n, p in events)
    assert "1" in final