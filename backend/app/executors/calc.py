from app.auth import require_role
from app.config import REFERENCE_NOW
from app.executors import data_lookup
from app.executors import policy_core as policy
from app.executors.data_lookup import READ_ROLES

def sla_deadline_tool(session, ticket_id, severity=None):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    
    tr = data_lookup.get_tickets(session, ticket_id=ticket_id)
    if tr["status"] != "ok" or not tr["tickets"]:
        return {"status": "not_found", "ticket_id": ticket_id}
    t = tr["tickets"][0]
    
    ar = data_lookup.get_account(session, t["account_id"])
    if ar["status"] != "ok":
        return {"status": "error", "detail": "account lookup failed"}
    account = ar["account"]
    
    sev_info= policy.classify_severity(f"{t.get('subject', '')} {t.get('description', '')}")
    sev = severity or sev_info["severity"]
    sla = policy.sla_for(account["account_id"], account["plan"], sev)
    start = policy.parse_dt(t.get("created_at")) or REFERENCE_NOW
    deadline = policy.sla_deadline(sla, start)
    # Breached = the customer's last reply came after the deadline (or the
    # deadline passed with no reply at all). Never states a breach from memory.
    last_msg = policy.parse_dt(t.get("last_customer_message_at"))
    breached = deadline < (last_msg if last_msg else REFERENCE_NOW)

    result = {
        "status": "ok",
        "ticket_id": t["ticket_id"],
        "severity": sev,
        "signals": sev_info["signals"],
        "source": sla["source"],
        "coverage": sla["coverage"],
        "sla_value": f"{sla['value']} {sla['unit']}",
        "start": start.isoformat(sep=" ", timespec="minutes"),
        "deadline": deadline.isoformat(sep=" ", timespec="minutes"),
        "breached": breached,
    }
    if sla.get("deprecated_v2_value"):
        v2 = sla["deprecated_v2_value"]
        result["note_v2"] = (
            f"Policy v2 (DEPRECATED) would have been {v2['value']} {v2['unit']}"
        )
    return result

def cancellation_check_tool(session, order_id):
    """Cancellation check from SOP v4 + agreement overrides + KI caveats."""
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    ors = data_lookup.get_orders(session, order_id=order_id)
    if ors["status"] != "ok" or not ors["orders"]:
        return {"status": "not_found", "order_id": order_id}
    order = ors["orders"][0]
    ar = data_lookup.get_account(session, order["account_id"])
    account = ar.get("account") if ar["status"] == "ok" else None
    return {"status": "ok", "result": policy.check_cancellation(order, account)}


def credit_check_tool(session, order_id):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    
    ors = data_lookup.get_orders(session, order_id=order_id)
    if ors["status"] != "ok" or not ors["orders"]:
        return {"status": "not_found", "order_id": order_id}
    
    order = ors["orders"][0]
    ar = data_lookup.get_account(session, order["account_id"])
    account = ar.get("account") if ar["status"] == 'ok' else None
    return {"status": 'ok', "result": policy.calculate_credit_eligibility(order, account)}

def classify_severity_tool(session, text):
    if not require_role(session, *READ_ROLES):
        return{"status": "permission_denied"}
    
    info = policy.classify_severity(text)
    return {"status": 'ok', "severity": info["severity"], "signals": info["signals"]}

