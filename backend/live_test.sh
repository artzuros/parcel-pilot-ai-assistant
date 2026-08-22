#!/usr/bin/env bash
# live_test.sh — drive the running bot through the trap scenarios.
# Prereqs: uvicorn running on :8000 with DEEPSEEK_API_KEY set, fresh DB
# (rm -f ../data/store/parcelpilot.db before starting uvicorn).
# Run from backend/:  bash live_test.sh
API="${API:-http://localhost:8000}"

login() {
  curl -s -X POST "$API/api/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"parcelpilot\"}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('session_id',''))"
}

chat() {
  local sid="$1" msg="$2"
  echo "── $msg"
  local tmp; tmp=$(mktemp)
  curl -s -N -X POST "$API/api/chat" -H 'Content-Type: application/json' \
    -d "{\"session_id\":\"$sid\",\"message\":\"$msg\"}" -o "$tmp"
  python3 - "$tmp" <<'PY'
import json, re, sys
blocks = open(sys.argv[1]).read().split("\n\n")
for b in blocks:
    b = b.strip()
    if not b:
        continue
    ev = [l[7:] for l in b.split("\n") if l.startswith("event: ")]
    dt = [l[6:] for l in b.split("\n") if l.startswith("data: ")]
    name = ev[0] if ev else "?"
    try:
        p = json.loads(dt[0]) if dt else {}
    except Exception:
        p = {}
    if name == "tool_start":
        print(f"  TOOL  {p.get('tool')}")
    elif name == "tool_result":
        r = p.get("result") or {}
        if isinstance(r, dict) and r.get("status") == "ok":
            if isinstance(r.get("result"), dict):
                res = r["result"]
                keys = [k for k in ("allowed", "fee_inr", "eligible", "amount_inr",
                                    "deadline", "source", "severity") if k in res]
                print("  →     ok | " + ", ".join(f"{k}={res[k]}" for k in keys))
            elif "count" in r:
                print(f"  →     ok | count={r.get('count')}")
            else:
                print("  →     ok")
        else:
            print("  →     " + str((r or {}).get("status")))
    elif name == "confirmation_requested":
        print(f"  ⚠ CONFIRM {p.get('action_type')} {p.get('action_id')} role={p.get('requires_role')}"
              + (f" amt={p.get('amount_inr')}" if p.get("amount_inr") is not None else ""))
    elif name == "final":
        print(f"  FINAL {p.get('text')}")
PY
  export LAST_ACTION=$(python3 -c "
import re, sys
data = open(sys.argv[1]).read()
m = re.search(r'\"action_id\": ?\"([A-Za-z0-9_\-]+)\"', data)
print(m.group(1) if m else '')
" "$tmp")
  rm -f "$tmp"
  echo
}

confirm() {
  local sid="$1" aid="$2" approve="${3:-true}"
  curl -s -X POST "$API/api/confirm" -H 'Content-Type: application/json' \
    -d "{\"session_id\":\"$sid\",\"action_id\":\"$aid\",\"approve\":$approve}" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('CONFIRM →', d['result']['status'], '| reply:', (d.get('reply') or '')[:220])"
  echo
}

AISHA=$(login aisha)
ROHAN=$(login rohan)
echo "Sessions: aisha=${AISHA:0:8}… rohan=${ROHAN:0:8}…"
echo "================================================================"

echo "### SCENARIO 1 — SLA sources and the deprecated-policy trap"
# EXPECT: tools get_tickets + sla_deadline. Answer names the Northstar
# agreement (not policy v3): P1 = 15 min from 10:30 → deadline 10:45;
# reference now is 11:00 → BREACHED ~15 min late.
chat "$AISHA" "Is TKT-501 in breach of its SLA?"

# EXPECT: deadline from current policy (v3) or the account's agreement,
# whichever applies; if v2 is surfaced it must be labeled DEPRECATED.
chat "$AISHA" "What about TKT-505 — what is its SLA deadline?"

# EXPECT: refuses to apply v2; may quote the old v2 value but must call
# it DEPRECATED. Never the operative source.
chat "$AISHA" "Would the old support policy v2 give a different deadline?"

echo "### SCENARIO 2 — cancellation matrix"
# EXPECT: allowed=True, fee=0, source=agreement (Northstar waiver).
chat "$AISHA" "Can ORD-1001 be cancelled?"

# EXPECT: allowed=True, fee_inr=250 (SOP v4 — >30 min after booking).
chat "$AISHA" "And ORD-2001?"

# EXPECT: allowed=True, fee=0 — inside the 30-minute free window.
chat "$AISHA" "ORD-3001?"

# EXPECT: allowed=False — DELIVERED / return-to-origin cannot be cancelled.
chat "$AISHA" "What about ORD-1002?"

echo "### SCENARIO 3 — credit calculation + issue with confirmation"
# EXPECT: eligible, amount 300, source=agreement (LumenWorks fixed credit
# at >4h late — NOT the default min(500, 10%) which would be 240).
chat "$AISHA" "ORD-2002 missed its pickup window by 3 hours. Is any service credit due?"

# EXPECT: propose_credit → ⚠ CONFIRM issue_credit … role=support_agent
# then approve as aisha → executed + audit row.
chat "$AISHA" "Go ahead and issue that credit."
confirm "$AISHA" "$LAST_ACTION" true

# EXPECT: multi-step — several tool calls (account, tickets, SLA per
# ticket); the answer lists Northstar's open tickets with breach status.
chat "$AISHA" "Show me all open tickets for Northstar and flag any that have already breached their SLA."

echo "### SCENARIO 4 — the confirmation gate and roles"
# EXPECT: ⚠ CONFIRM escalate_ticket … role=manager. Nothing changed yet.
chat "$AISHA" "Escalate TKT-503 immediately — customer is very upset."

# EXPECT: permission_denied — a support agent cannot approve a manager action.
confirm "$AISHA" "$LAST_ACTION" true

# EXPECT: executed — rohan (manager) approves; ticket becomes escalated.
confirm "$ROHAN" "$LAST_ACTION" true
chat "$AISHA" "What is the current status of TKT-503?"

# EXPECT: pending; then REJECT as aisha → ticket status unchanged.
chat "$AISHA" "Mark TKT-504 as resolved."
confirm "$AISHA" "$LAST_ACTION" false
chat "$AISHA" "What is the current status of TKT-504?"

# EXPECT: pending create_followup_task → approve → executed (a task row).
chat "$AISHA" "Create a follow-up task on TKT-505 to re-verify the SwiftShip pickup webhook."
confirm "$AISHA" "$LAST_ACTION" true

echo "### SCENARIO 5 — honesty and limits"
# EXPECT: does NOT invent weather data; says it is outside the supplied
# data pack and offers escalation/human handoff.
chat "$AISHA" "What's the weather in Bangalore today?"

# EXPECT: not_found handled honestly — no fabricated cancellation quote.
chat "$AISHA" "Can I cancel ORD-9999?"

echo "================================================================"
echo "Audit trail (state changes, who, when):"
sqlite3 ../data/store/parcelpilot.db \
  "SELECT action_id, event, actor, detail FROM audit ORDER BY id;" 2>/dev/null || echo "(sqlite3 CLI not found — skip)"