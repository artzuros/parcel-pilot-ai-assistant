from datetime import datetime, timedelta
from app.config import REFERENCE_NOW

# working hours assumed
BUSINESS_HOURS = {"start":9, "end":18}
BUSINESS_DAYS = {0,1,2,3,4}

SLA_POLICY_V3 = {
    "enterprise": {
        "P1":{"value": 30, "unit": "minute", "coverage": "24x7"},
        "P2":{"value": 2, "unit": "hour", "coverage": "business_hours"},
        "P3":{"value": 1, "unit": "business_day", "coverage": "business_hours"}
    },
    "growth": {
        "P1":{"value": 2, "unit": "business_hour", "coverage": "business_hours"},
        "P2":{"value": 4, "unit": "business_hour", "coverage": "business_hours"},
        "P3":{"value": 2, "unit": "business_day", "coverage": "business_hours"}
    },
    "standard": {
        "P1":{"value": 4, "unit": "business_hour", "coverage": "business_hours"},
        "P2":{"value": 1, "unit": "business_day", "coverage": "business_hours"},
        "P3":{"value": 2, "unit": "business_day", "coverage": "business_hours"}
    },
}

SLA_POLICY_V2 = {
    "enterprise": {
        "P1":{"value": 1, "unit": "hour"},
        "P2":{"value": 4, "unit": "hour"},
        "P3":{"value": 2, "unit": "business_day"}
    },
    "growth": {
        "P1": {"value": 4, "unit": "business_hour"},
        "P2": {"value": 1, "unit": "business_day"},
        "P3": {"value": 3, "unit": "business_day"},
    },
    "standard": {
        "P1": {"value": 8, "unit": "business_hour"},
        "P2": {"value": 2, "unit": "business_day"},
        "P3": {"value": 3, "unit": "business_day"},
    },
}

AGREEMENT_SLA_OVERRIDES = {
    "ACCT-001": {  # Northstar  agreement (05)
        "P1": {"value": 15, "unit": "minute",       "coverage": "24x7"},
        "P2": {"value": 1,  "unit": "hour",         "coverage": "business_hours"},
        "P3": {"value": 8,  "unit": "business_hour","coverage": "business_hours"},
    },
    "ACCT-002": {  # LumenWorks  agreement (06)
        "P1": {"value": 2, "unit": "business_hour",  "coverage": "business_hours"},
        "P2": {"value": 4, "unit": "business_hour",  "coverage": "business_hours"},
        "P3": {"value": 2, "unit": "business_day",   "coverage": "business_hours"},
    },
}

CANCELLATION_FEE_INR = 250
FREE_CANCELLATION_WINDOW_MINUTES = 30
CANCELLATION_FEE_WAIVER_ACCOUNTS = {"ACCT-001"}

DEFAULT_CREDIT_THRESHOLD_HOURS = 2
DEFAULT_CREDIT_CAP_INR = 500
DEFAULT_CREDIT_PERCENT = 0.10

MANAGER_APPROVAL_THRESHOLD_INR = 1000

CREDIT_OVERRIDES = {
    "ACCT-002": {"threshold_hours": 4, "amount_inr": 300},
}

MONTHLY_CREDIT_CAP = {"ACCT-001": 5000}

def parse_dt(value):
    if value is None: return None
    return datetime.fromisoformat(str(value).strip())

def is_business_day(dt):
    return dt.weekday() in BUSINESS_DAYS

def is_business_hour(dt):
    return is_business_day(dt) and BUSINESS_HOURS["start"] <= dt.hour < BUSINESS_HOURS["end"]

def next_business_day_open(dt):
    d = dt + timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d.replace(hour=BUSINESS_HOURS["start"], minute=0, second=0, microsecond=0)

def add_business_hours(start, value):
    remaining = float(value)
    cur = start
    while remaining > 1e-9:
        if not is_business_day(cur) or cur.hour >= BUSINESS_HOURS["end"]:
            cur = next_business_day_open(cur)
            continue
        if cur.hour < BUSINESS_HOURS["start"]:
            cur = cur.replace(hour=BUSINESS_HOURS["start"], minute=0, second=0, microsecond=0)
            continue
        window_end = cur.replace(hour=BUSINESS_HOURS["end"], minute=0, second=0, microsecond=0)
        avail_hours = (window_end - cur).total_seconds() / 3600.0
        if avail_hours >= remaining:
            cur = cur + timedelta(hours=remaining)
            remaining = 0.0
        else:
            remaining -= avail_hours
            cur = next_business_day_open(cur)
    return cur

def business_day_deadline(start, value):
    if is_business_day(start) and start.hour < BUSINESS_HOURS["end"]:
        cur = start.replace(hour=BUSINESS_HOURS["start"], minute=0, second=0, microsecond=0)
    else:
        cur = next_business_day_open(start)
    for _ in range(value-1):
        cur = next_business_day_open(cur)
    return cur.replace(hour=BUSINESS_HOURS["end"], minute=0, second=0, microsecond=0)

def sla_deadline(sla, start):
    unit = sla["unit"]
    if unit == "minute":
        return start + timedelta(minutes=sla["value"])
    if unit == "hour":
        return start + timedelta(hours=sla["value"])
    if unit == "business_hour":
        return add_business_hours(start, sla["value"])
    if unit == "business_day":
        return business_day_deadline(start, sla["value"])
    raise ValueError(f"Unknown SLA unit: {unit}")



def _v2(plan, severity):
    try:
        return SLA_POLICY_V2[plan.lower()][severity]
    except KeyError: return None
    

def sla_for(account_id, plan, severity):
    override = AGREEMENT_SLA_OVERRIDES.get(account_id, {}).get(severity)
    if override is not None:
        return {
            **override,
            "account_id" : account_id,
            "source" : "agreement",
            "deprecated_v2_value": _v2(plan, severity),
        }
    return {
        **SLA_POLICY_V3[plan.lower()][severity],
        "account_id" : account_id,
        "source" : "policy_v3",
        "deprecated_v2_value": _v2(plan, severity),
    }
    
def has_weekend_coverage(account_id, severity):
    if account_id in ("ACCT-001", ):
        return sla_for(account_id, "enterprise", severity)["coverage"] == "24x7"
    return False


SEVERITY_RULES = [
    ("P1", [
        "http 500", "production outage", "shipment creation", "credential",
        "api key", "security incident", "breach", "data leak",
    ]),
    ("P2", [
        "bulk upload", "webhook", "degraded", "feature unavailable",
        "still shows", "not updating", "intermittent",
    ]),
    ("P3", [
        "how do", "how to", "billing contact", "configuration", "config request",
    ]),
]

def classify_severity(text):
    t = ((text or "")).lower()
    for severity, keywords in SEVERITY_RULES:
        hits = [k for k in keywords if k in t]
        if hits: return {"severity": severity, "signals": hits}
    return {"severity": "P3", "signals": []}

def check_cancellation(order, account=None, now=None):
    now = now or REFERENCE_NOW
    result = {
        "order_id": order.get("order_id"),
        "status": order.get("status"),
        "allowed": None,
        "fee_inr": 0,
        "reason": "",
        "source": "sop_v4",
        "caveats": [],
    }
    status = order.get("status")
    
    if status == "DRAFT":
        result.update(allowed=True, reason="DRAFT shipments may be cancelled with no fee.")
    elif status == "DELIVERED":
        result.update(allowed=False, reason="DELIVERED shipments cannot be cancelled.")
    elif status == "PICKED_UP":
        result.update(
            allowed=False,
            reason="PICKED_UP shipments cannot be cancelled; use the return-to-origin workflow.",
        )
    elif status == "BOOKED":
        if account and account.get("account_id") in CANCELLATION_FEE_WAIVER_ACCOUNTS:
            result.update(
                allowed=True, fee_inr=0, source="agreement",
                reason="Customer agreement waives the cancellation fee for BOOKED shipments "
                       "(Northstar Enterprise Agreement).",
            )
        else: 
            anchor = parse_dt(order.get("cancellation_requested_at")) or now
            booked = parse_dt(order.get("booked_at"))
            age_min = (anchor - booked).total_seconds() / 60.0 if booked else None
            if age_min is not None and age_min <= FREE_CANCELLATION_WINDOW_MINUTES:
                result.update(
                    allowed=True, fee_inr=0,
                    reason=f"No cancellation fee within 30 minutes of booking "
                            f"(cancellation requested {age_min:.0f} min after booking).",
                    )
            else:
                result.update(
                    allowed=True, fee_inr=CANCELLATION_FEE_INR,
                    reason=f"INR {CANCELLATION_FEE_INR} cancellation fees applies after {FREE_CANCELLATION_WINDOW_MINUTES} minutes"
                    f" from booking (requested {age_min:.0f} min after booking).",
                )
        if order.get("carrier") == "SwiftShip" and not order.get("pickup_actual_at"):
            result["caveats"].append(
                "KI-211: SwiftShip pickup webhooks can arrive up to 20 min late — "
                    "verify carrier status before stating the pickup did not occur."
            )
    else: result.update(allowed=False, reason=f"Unknown order status: {status}.")
    return result


def calculate_credit_eligibility(order, account=None, now=None):
    now = now or REFERENCE_NOW
    result = {
        "order_id": order.get("order_id"),
        "account_id": account.get("account_id") if account else None,
        "eligible": False,
        "amount_inr": 0,
        "reason": "",
        "approval_required": False,
        "source": "sop_v4",
        "caveats": [],
    }
    
    carrier_fault = order.get("carrier_fault")
    customer_fault = order.get("customer_fault")
    
    if carrier_fault is None or customer_fault is None:
        result["reason"] = ("Fault determination is unknown - dont promise a credit; "
                            "request verification before any state-changing action.")
        return result
    if customer_fault:
        result["reason"] = "Customer-caused issue present - not eligible for a failed-pickup credit."
        return result
    if not carrier_fault:
        result["reason"] = "Carrier not at fault — not eligible for a failed-pickup credit."
        return result
    
    window_end = parse_dt(order.get("pickup_window_end"))
    if window_end is None:
            result["reason"] = ("Pickup timing is unknown (no pickup window) — do not promise "
                            "a credit; request verification.")
            return result
    pickup_at = parse_dt(order.get("pickup_actual_at"))
    reference = pickup_at if pickup_at else now
    delay_hours = (reference - window_end).total_seconds() / 3600.00
    account_id = account.get("account_id") if account else None
    override = CREDIT_OVERRIDES.get(account_id) if account_id else None
    
    if override:
        if delay_hours > override["threshold_hours"]:
            result.update(
                eligible=True, amount_inr=override["amount_inr"], source="agreement",
                reason=(f"Agreement (LumenWorks): pickup {delay_hours:.1f}h past window end "
                        f"with carrier fault -> fixed INR {override['amount_inr']} credit."),
            )
        else:
            result["reason"] = (f"Agreement threshold not met: {delay_hours:.1f}h past the "
                                f"window end, need more than {override['threshold_hours']}h.")
            return result
    else:
        if delay_hours > DEFAULT_CREDIT_THRESHOLD_HOURS:
            fee = order.get("shipment_fee_inr")
            if fee is None:
                result["reason"] = ("Shipment fee missing - cannot compute the default "
                                    "credit amount; request verification.")
                return result
            amount = min(DEFAULT_CREDIT_CAP_INR, int(round(DEFAULT_CREDIT_PERCENT * fee)))

            result.update(
                eligible=True, amount_inr=amount,
                reason=f"SOP v4: Pickup {delay_hours:.1f}h past window end with carrier "
                f"fault -> min(INR 500, 10% of fee) = INR {amount}.",
            )
        else:
            result["reason"] = (f"Threshold not met: {delay_hours:.1f}h past the window "
                                f"end, need more than {DEFAULT_CREDIT_THRESHOLD_HOURS}h.")
            return result
    
    if result["amount_inr"] > MANAGER_APPROVAL_THRESHOLD_INR:
        result["approval_required"] = True
        result["reason"] += " Manager approval required (credit > INR 1,000)."
    if account_id in MONTHLY_CREDIT_CAP:
        result["monthly_cap_inr"] = MONTHLY_CREDIT_CAP[account_id]
    return result 