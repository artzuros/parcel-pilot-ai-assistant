import json, pathlib

from app.data.db import get_connection

ROOT = pathlib.Path(__file__).resolve().parents[3]
SEED_DIR = ROOT / "data" / "seed"

def _rows(name):
    return json.loads((SEED_DIR / f"{name}.json").read_text(encoding="utf-8"))

def seed_if_empty():
    conn = get_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] > 0:
            return False
        for a in _rows("accounts"):
            conn.execute(
                """INSERT INTO accounts (account_id, account_name, plan, status, csm,
                contract_file, premium_support, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (a["account_id"], a["account_name"], a["plan"], a["status"],
                a.get("csm"), a.get("contract_file"),
                int(bool(a.get("premium_support"))), a.get("notes")),
            )
        for o in _rows("orders"):
            conn.execute(
                """INSERT INTO orders (order_id, account_id, carrier, status, booked_at,
                    pickup_window_start, pickup_window_end, pickup_actual_at,
                    shipment_fee_inr, carrier_fault, customer_fault,
                    cancellation_requested_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (o["order_id"], o["account_id"], o.get("carrier"), o["status"],
                o.get("booked_at"), o.get("pickup_window_start"),
                o.get("pickup_window_end"), o.get("pickup_actual_at"),
                o.get("shipment_fee_inr"), o.get("carrier_fault"),
                o.get("customer_fault"), o.get("cancellation_requested_at"),
                o.get("notes")),
            )
        for t in _rows("tickets"):
            conn.execute(
                """INSERT INTO tickets (ticket_id, account_id, created_at, status, subject,
                    description, channel, assigned_to, last_customer_message_at,
                    historical_resolution, resolution_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (t["ticket_id"], t["account_id"], t.get("created_at"), t["status"],
                t.get("subject"), t.get("description"), t.get("channel"),
                t.get("assigned_to"), t.get("last_customer_message_at"),
                t.get("historical_resolution"), t.get("resolution_confidence")),
            )
        conn.commit()
        return True
    finally: conn.close()