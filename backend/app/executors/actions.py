import uuid

from app.auth import require_role
from app.config import REFERENCE_NOW
from app.data import store
from app.data.db import get_connection
from app.executors import calc
from app.executors.data_lookup import READ_ROLES, get_tickets


TICKET_UPDATE_FIELDS = {"status", "assigned_to"}

def _new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

def _require_ticket(session, ticket_id):
    tr=get_tickets(session, ticket_id=ticket_id)
    if tr["status"] != "ok" or not tr["tickets"]:
        return False
    return True

def escalate_ticket(session, ticket_id, reason=""):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}

    if not _require_ticket(session, ticket_id):
        return {"status": "not_found", "ticket_id": ticket_id}

    action_id = store.create_pending(
        "escalate_ticket", session["session_id"],
        {"ticket_id": ticket_id, "reason": reason,
        "created_by": session.get("username", "unkown")}, "manager")

    return {"status":"pending", "action_id": action_id,
            "requires_confirmation": True, "requires_role": "manager",
            "message": f"Escalating {ticket_id} requires a manager to confirm."}


def update_ticket(session, ticket_id, field, value):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}

    if field not in TICKET_UPDATE_FIELDS:
        return {"status" : "error",
                "detail": f"field must be one of {sorted(TICKET_UPDATE_FIELDS)}"}

    if not _require_ticket(session, ticket_id):
        return {"status": "not_found", "ticket_id": ticket_id}

    action_id = store.create_pending(
        "update_ticket", session["session_id"],
        {"ticket_id": ticket_id, "field": field, "value": value,
         "created_by": session.get("username", "unknown")},
        "support_agent"
    )
    return {"status": "pending", "action_id": action_id,
            "requires_confirmation": True, "requires_role": "support_agent",
            "message": f"Update of {ticket_id} awaits confirmation."
            }


def create_followup_task(session, ticket_id, description, due_at = None):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}

    if not _require_ticket(session, ticket_id):
        return {"status": "not_found", "ticket_id": ticket_id}

    action_id = store.create_pending(
        "create_followup_task", session["session_id"],
        {"ticket_id": ticket_id, "description": description, "due_at": due_at,
         "created_by": session.get("username", "unknown")},
        "support_agent")

    return {"status": "pending", "action_id": action_id,
            "requires_confirmation": True, "requires_role": "support_agent",
            "message": f"Follow-up task for {ticket_id} awaits confirmation."
            }

def propose_credit(session, order_id):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}

    r = calc.credit_check_tool(session, order_id)
    if r["status"] != "ok": return r

    res = r["result"]
    if not res["eligible"]:
        return {"status": "not_eligible", "reason": res["reason"]}

    requires_role = "manager" if res.get("approval_required") else "support_agent"
    action_id = store.create_pending(
        "issue_credit", session["session_id"],
        {"order_id": order_id, "amount_inr": res["amount_inr"],
        "reason": res["reason"], "issued_by": session.get("username", "unknown")
        },
        requires_role
    )

    return {"status": "pending", "action_id": action_id,
            "amount_inr": res["amount_inr"],
            "approval_required": res.get("approval_required", False),
            "requires_confirmation": True, "requires_role": requires_role,
            "message": f"Credit of INR {res['amount_inr']} for {order_id} awaits confirmation."
        }

def confirm_action(session, action_id, approve=True):
    p = store.get_pending(action_id)
    if p is None:
        return {"status": "not_found", "action_id": action_id}
    if p["status"] != "pending":
        return {"status": "already_handled", "action_id": action_id,
                "current_status": p["status"]}

    if store.is_expired(p):
        store.mark_action(action_id, "expired")
        store.log_audit(session.get("username", "?"), action_id, "action_expired", "confirmation TTL exceeded")
        return {"status": "expired", "action_id": action_id}
    
    if not require_role(session, p["requires_role"]) and session.get("role") != "admin":
        return {"status": "permission_denied", "action_id": action_id,
                "detail": f"{p['action_type']} requires role {p['requires_role']}"}
    if not approve:
        store.mark_action(action_id, "rejected")
        store.log_audit(session.get("username", "?"), action_id, "action.rejected", "declined by user")
        return {"status": "rejected", "action_id": action_id}

    _EXECUTORS[p["action_type"]](p["payload"])
    store.mark_action(action_id, "executed")
    store.log_audit(session.get("username", "?"), action_id, "action.executed",
                    f"{p['action_type']} {p['payload']}")

    return {"status": "executed", "action_id": action_id,
            "action_type": p["action_type"]}



_EXECUTORS = {}
def _register(kind):
    def deco(fn):
        _EXECUTORS[kind] = fn
        return fn
    return deco

@_register("escalate_ticket")
def _exec_escalate(payload):
    conn = get_connection()
    try:
        conn.execute("UPDATE tickets SET status = 'escalated' WHERE ticket_id = ?", (payload["ticket_id"], ))
        conn.commit()
    finally: conn.close()


@_register("update_ticket")
def _exec_update(payload):
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE tickets SET {payload['field']} = ? WHERE ticket_id = ?",
            (payload["value"], payload["ticket_id"]))
        conn.commit()
    finally:
        conn.close()


@_register("create_followup_task")
def _exec_task(payload):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO tasks (task_id, ticket_id, description, due_at, status,created_at, created_by) VALUES (?, ?, ?, ?, 'open', ?, ?)""",
            (_new_id("TASK"), payload["ticket_id"], payload["description"],
            payload.get("due_at"),
            REFERENCE_NOW.isoformat(sep=" ", timespec="minutes"),
            payload.get("created_by")))
        conn.commit()
    finally:
        conn.close()


@_register("issue_credit")
def _exec_credit(payload):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO credits (credit_id, order_id, amount_inr, status,issued_at, issued_by) VALUES (?, ?, ?, 'issued', ?, ?)""",
            (_new_id("CR"), payload["order_id"], payload["amount_inr"],
            REFERENCE_NOW.isoformat(sep=" ", timespec="minutes"),
            payload.get("issued_by")))
        conn.commit()
    finally:
        conn.close()

def list_pending_approvals(session):
    """Read-only: actions awaiting approval by the session's role."""
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    return {"status": "ok",
            "approvals": [p for p in store.list_pending()
                          if require_role(session, p["requires_role"])]}
