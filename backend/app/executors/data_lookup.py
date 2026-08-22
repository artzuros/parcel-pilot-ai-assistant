from app.auth import require_role
from app.data.db import get_connection

READ_ROLES = {"support_agent", "manager", "admin"}

def _to_bool(v):
    return None if v is None else bool(v)

def _account_row(r):
    return {
        "account_id":r["account_id"], "account_name": r["account_name"],
        "plan": r["plan"], "status": r["status"], "csm": r["csm"],
        "contract_file": r["contract_file"],
        "premium_support": _to_bool(r["premium_support"]),
        "notes": r["notes"],
    }


def _order_row(r):
    fee = r["shipment_fee_inr"]
    return {
        "order_id": r["order_id"], "account_id": r["account_id"],
        "carrier": r["carrier"], "status": r["status"],
        "booked_at": r["booked_at"],
        "pickup_window_start": r["pickup_window_start"],
        "pickup_window_end": r["pickup_window_end"],
        "pickup_actual_at": r["pickup_actual_at"],
        "shipment_fee_inr": int(fee) if fee is not None else None,
        "carrier_fault": _to_bool(r["carrier_fault"]),
        "customer_fault": _to_bool(r["customer_fault"]),
        "cancellation_requested_at": r["cancellation_requested_at"],
        "notes": r["notes"],
    }


def _ticket_row(r):
    return {
        "ticket_id": r["ticket_id"], "account_id": r["account_id"],
        "created_at": r["created_at"], "status": r["status"],
        "subject": r["subject"], "description": r["description"],
        "channel": r["channel"], "assigned_to": r["assigned_to"],
        "last_customer_message_at": r["last_customer_message_at"],
        "historical_resolution": r["historical_resolution"],
        "resolution_confidence": r["resolution_confidence"],
    }


def get_orders(session, order_id=None, account_id=None, status=None):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    clauses, params = [], []
    
    if order_id:
        clauses.append("order_id = ?"); params.append(order_id)
    if account_id:
        clauses.append("account_id = ?"); params.append(account_id)
    if status:
        clauses.append("LOWER(status) = LOWER(?)"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_connection()
    try:
        rows = conn.execute(f"SELECT * FROM orders {where} ORDER BY order_id",
                            params).fetchall()
        return {"status": "ok", "orders": [_order_row(r) for r in rows]}
    finally: conn.close()

def get_tickets(session, ticket_id=None, account_id=None, status=None):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    clauses, params = [], []
    if ticket_id:
        clauses.append("ticket_id = ?"); params.append(ticket_id)
    if account_id:
        clauses.append("account_id = ?"); params.append(account_id)
    if status:
        clauses.append("LOWER(status) = LOWER(?)"); params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_connection()
    try:
        rows = conn.execute(f"SELECT * FROM tickets {where} ORDER BY ticket_id",
                            params).fetchall()
        return {"status": "ok", "tickets": [_ticket_row(r) for r in rows]}
    finally:
        conn.close()

def get_account(session, account_id=None, name=None):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    conn = get_connection()
    try:
        row = None
        if account_id:
            row = conn.execute("SELECT * FROM accounts WHERE account_id = ?",
                            (account_id,)).fetchone()
        if row is None and name:
            row = conn.execute(
                "SELECT * FROM accounts WHERE LOWER(account_name) LIKE ?",
                (f"%{name.lower()}%",)).fetchone()
        if row is None:
            return {"status": "not_found", "query": account_id or name}
        return {"status": "ok", "account": _account_row(row)}
    finally:
        conn.close()
