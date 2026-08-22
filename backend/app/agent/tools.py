from app.auth import require_role
from app.executors import actions, calc
from app.executors import data_lookup as dl
from app.executors.data_lookup import READ_ROLES
from app.executors.doc_search import doc_search_tool

def _t(name, description, parameters, handler):
    return {"name": name, "description": description, "parameters": parameters, "handler": handler}

def _h_doc_search(session, args):
    if not require_role(session, *READ_ROLES):
        return {"status": "permission_denied"}
    return doc_search_tool(query=args.get("query", ""),
                        max_results=args.get("max_results", 4))
    
def _h_get_account(session, args):
    return dl.get_account(session, account_id=args.get("account_id"), name=args.get("name"))

def _h_get_orders(session, args):
    return dl.get_orders(session, order_id=args.get("order_id"), account_id=args.get("account_id"), status=args.get("status"))

def _h_get_tickets(session, args):
    return dl.get_tickets(session, ticket_id=args.get("ticket_id"),
                        account_id=args.get("account_id"), status=args.get("status"))

def _h_sla(session, args):
    return calc.sla_deadline_tool(session, args.get("ticket_id"),
                                severity=args.get("severity"))

def _h_cancel(session, args):
    return calc.cancellation_check_tool(session, args.get("order_id"))

def _h_credit(session, args):
    return calc.credit_check_tool(session, args.get("order_id"))

def _h_severity(session, args):
    return calc.classify_severity_tool(session, args.get("text", ""))

def _h_escalate(session, args):
    return actions.escalate_ticket(session, args.get("ticket_id"),
                                args.get("reason", ""))


def _h_update(session, args):
    return actions.update_ticket(session, args.get("ticket_id"),
                                args.get("field"), args.get("value"))


def _h_task(session, args):
    return actions.create_followup_task(session, args.get("ticket_id"),
                                        args.get("description"),
                                        args.get("due_at"))

def _h_propose_credit(session, args):
    return actions.propose_credit(session, args.get("order_id"))

TOOLS = [
    _t("doc_search",
       "Search ParcelPilot's internal documentation (support policy, SOPs, "
       "product guide, agreements). Use it for any policy or procedure question. "
       "Results carry each document's status (CURRENT/DEPRECATED).",
       {"type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "What to look up, e.g. 'cancellation fee', "
                                     "'P1 SLA', 'bulk upload limits'"},
            "max_results": {"type": "integer",
                            "description": "Max chunks to return (default 4)"}},
        "required": ["query"]},
       _h_doc_search),

    _t("get_account",
       "Look up a customer account by account_id (e.g. ACCT-001) or name "
       "(e.g. Northstar). Returns plan, status, premium support flag.",
       {"type": "object",
        "properties": {
            "account_id": {"type": "string", "description": "e.g. ACCT-001"},
            "name": {"type": "string", "description": "e.g. Northstar"}},
        "required": []},
       _h_get_account),

    _t("get_orders",
       "Look up orders, optionally filtered by order_id, account_id, status.",
       {"type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "e.g. ORD-1001"},
            "account_id": {"type": "string", "description": "e.g. ACCT-001"},
            "status": {"type": "string",
                       "description": "e.g. BOOKED, DELIVERED, PICKED_UP"}},
        "required": []},
       _h_get_orders),

    _t("get_tickets",
       "Look up support tickets, optionally filtered by ticket_id, account_id, "
       "status. Results include resolution_confidence (suspect = do not trust).",
       {"type": "object",
        "properties": {
            "ticket_id": {"type": "string", "description": "e.g. TKT-501"},
            "account_id": {"type": "string", "description": "e.g. ACCT-001"},
            "status": {"type": "string", "description": "e.g. open, escalated"}},
        "required": []},
       _h_get_tickets),

    _t("sla_deadline",
       "Get the SLA response deadline for a ticket, from the account's signed "
       "agreement if one exists, else current policy v3. The deprecated v2 "
       "value is surfaced for transparency but never applied.",
       {"type": "object",
        "properties": {
            "ticket_id": {"type": "string", "description": "e.g. TKT-501"},
            "severity": {"type": "string",
                         "description": "optional override; P1, P2 or P3"}},
        "required": ["ticket_id"]},
       _h_sla),

    _t("cancellation_check",
       "Check whether an order can be cancelled and any fee, per SOP v4 and "
       "agreement overrides. Includes known-issue caveats.",
       {"type": "object",
        "properties": {"order_id": {"type": "string", "description": "e.g. ORD-1001"}},
        "required": ["order_id"]},
       _h_cancel),

    _t("credit_check",
       "Check service-credit eligibility and amount for an order, per SOP v4 "
       "and agreement overrides.",
       {"type": "object",
        "properties": {"order_id": {"type": "string", "description": "e.g. ORD-2002"}},
        "required": ["order_id"]},
       _h_credit),

    _t("classify_severity",
       "Classify free text into P1/P2/P3 using the severity rules.",
       {"type": "object",
        "properties": {"text": {"type": "string", "description": "issue text"}},
        "required": ["text"]},
       _h_severity),

    _t("escalate_ticket",
       "PROPOSE escalation of a ticket. Creates a pending action that a "
       "manager must confirm before it executes.",
       {"type": "object",
        "properties": {
            "ticket_id": {"type": "string", "description": "e.g. TKT-501"},
            "reason": {"type": "string", "description": "why it needs escalation"}},
        "required": ["ticket_id"]},
       _h_escalate),

    _t("update_ticket",
       "PROPOSE an update to a ticket (field must be 'status' or 'assigned_to'). "
       "Creates a pending action awaiting user confirmation.",
       {"type": "object",
        "properties": {
            "ticket_id": {"type": "string", "description": "e.g. TKT-503"},
            "field": {"type": "string",
                      "description": "one of: status, assigned_to"},
            "value": {"type": "string", "description": "new value, e.g. resolved"}},
        "required": ["ticket_id", "field", "value"]},
       _h_update),

    _t("create_followup_task",
       "PROPOSE a follow-up task on a ticket (e.g. verify a webhook). Creates "
       "a pending action awaiting user confirmation.",
       {"type": "object",
        "properties": {
            "ticket_id": {"type": "string", "description": "e.g. TKT-504"},
            "description": {"type": "string", "description": "what to do"},
            "due_at": {"type": "string", "description": "optional due datetime"}},
        "required": ["ticket_id", "description"]},
       _h_task),

    _t("propose_credit",
       "PROPOSE a service credit for an order (eligibility is computed by the "
       "policy engine). Creates a pending action; credits above INR 1,000 need "
       "manager confirmation.",
       {"type": "object",
        "properties": {"order_id": {"type": "string", "description": "e.g. ORD-2002"}},
        "required": ["order_id"]},
       _h_propose_credit),
]


TOOLS_SCHEMA = [{
    "type" : "function",
    "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in TOOLS]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}

def dispatch(name, session, args):
    t = TOOLS_BY_NAME.get(name)
    if t is None:return {"status": "error", "detail": f"unknown tool: {name}"}
    return t["handler"](session, args)