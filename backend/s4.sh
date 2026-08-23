#!/usr/bin/env bash
# s4.sh — scenario 4: the confirmation gate, roles, and the reject path.
# Prereqs: fresh DB + uvicorn on :8000 — rm -f ../data/store/parcelpilot.db
# BEFORE starting uvicorn. Run from backend/:  bash s4.sh
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
import json, sys
for b in open(sys.argv[1]).read().split("\n\n"):
    b = b.strip()
    if not b: continue
    ev = [l[7:] for l in b.split("\n") if l.startswith("event: ")]
    dt = [l[6:] for l in b.split("\n") if l.startswith("data: ")]
    name = ev[0] if ev else "?"
    try:
        p = json.loads(dt[0]) if dt else {}
    except Exception:
        p = {}
    if name == "tool_start":
        print(f"  TOOL  {p.get('tool')}")
    elif name == "confirmation_requested":
        print(f"  ⚠ CONFIRM {p.get('action_type')} {p.get('action_id')} role={p.get('requires_role')}")
    elif name == "final":
        print(f"  FINAL {p.get('text')}")
    elif not ev:
        print(f"  (non-SSE response: {b[:100]})")
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
  curl -s -X POST "$API/api/confirm" -H 'Content-Type: application/json' \
    -d "{\"session_id\":\"$1\",\"action_id\":\"$2\",\"approve\":$3}" \
    | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('CONFIRM →', d['result']['status'], '| reply:', (d.get('reply') or '')[:200])
except Exception as e:
    print('CONFIRM → could not parse response:', e)
"
  echo
}

AISHA=$(login aisha)
ROHAN=$(login rohan)
echo "Sessions: aisha=${AISHA:0:8}… rohan=${ROHAN:0:8}…"

# ── Beat 1: manager gate (routing) ────────────────────────────────────
# EXPECT: NO confirmation_requested — the action is submitted and routed to
# the manager. Reply says it awaits manager approval; LAST_ACTION captured.
chat "$AISHA" "TKT-501 has breached its SLA. Escalate it."
if [ -z "$LAST_ACTION" ]; then
  echo "  !! no action_id — submission failed"
fi

# EXPECT: permission_denied — aisha's role can't confirm it (backstop)
confirm "$AISHA" "$LAST_ACTION" true

# EXPECT: executed — rohan (manager) approves; reply reports executed
confirm "$ROHAN" "$LAST_ACTION" true

# EXPECT: status = escalated — aisha's history was rewritten, bot reports it
chat "$AISHA" "What is the current status of TKT-501?"

# ── Beat 2: policy judgment ───────────────────────────────────────────
# EXPECT (either): the bot checks ORD-1001, sees the symptom still present
# and refuses to resolve TKT-504 — OR proposes it. Both are fine; if it
# proposes, reject it so the gate is exercised and nothing dangles.
chat "$AISHA" "Mark TKT-504 as resolved."
if [ -n "$LAST_ACTION" ]; then
  confirm "$AISHA" "$LAST_ACTION" false
else
  echo "  (bot refused — policy judgment, expected)"
fi


# ── Beat 3: reject path ───────────────────────────────────────────────
# EXPECT: ⚠ CONFIRM create_followup_task … role=support_agent
chat "$AISHA" "Create a follow-up task on TKT-504 to re-verify the SwiftShip pickup webhook."

# EXPECT: rejected — no task created, audit row action.rejected
confirm "$AISHA" "$LAST_ACTION" false

# EXPECT: 0 rows — rejection really changed nothing
sqlite3 ../data/store/parcelpilot.db "SELECT COUNT(*) AS tasks FROM tasks;"

# ── Beat 4: execute path ──────────────────────────────────────────────
# EXPECT: ⚠ again, then executed
chat "$AISHA" "Go ahead and create that follow-up task on TKT-504."
confirm "$AISHA" "$LAST_ACTION" true

# EXPECT: 1 row — the task exists now
sqlite3 ../data/store/parcelpilot.db "SELECT COUNT(*) AS tasks FROM tasks;"

echo "Audit trail:"
sqlite3 ../data/store/parcelpilot.db "SELECT action_id, event, actor FROM audit ORDER BY id;" 2>/dev/null
