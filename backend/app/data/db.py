import pathlib, sqlite3

ROOT = pathlib.Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "data" / "store" / "parcelpilot.db"

SCHEMA = """

CREATE TABLE IF NOT EXISTS accounts(
    account_id TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,
    csm TEXT,
    contract_file TEXT,
    premium_support INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS orders(
    order_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    carrier TEXT,
    status TEXT NOT NULL,
    booked_at TEXT,
    pickup_window_start TEXT,
    pickup_window_end TEXT,
    pickup_actual_at TEXT,
    shipment_fee_inr REAL,
    carrier_fault INTEGER,
    customer_fault INTEGER,
    cancellation_requested_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS tickets(
    ticket_id PRIMARY KEY,
    account_id TEXT NOT NULL,
    created_at TEXT,
    status TEXT NOT NULL,
    subject TEXT,
    description TEXT,
    channel TEXT,
    assigned_to TEXT,
    last_customer_message_at TEXT,
    historical_resolution TEXT,
    resolution_confidence TEXT
);

CREATE TABLE IF NOT EXISTS actions(
    action_id TEXT PRIMARY KEY,
    session_id TEXT,
    action_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    requires_role TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    executed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT,
    action_id TEXT,
    event TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL
);
"""

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()