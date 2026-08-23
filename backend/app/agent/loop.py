import json

from app.agent import tools
from app.agent.system_prompt import SYSTEM_PROMPT
from app.config import REFERENCE_NOW
from app.executors import actions
from app.llm import deepseek
from app import budget
from app.agent.args_models import validate_args

MAX_TOOL_TURNS = 6
CHATS = {}
# action_id -> where its pending tool response lives, so a confirmation
# (possibly from a different session) can rewrite it IN PLACE with the
# outcome. The API requires every tool_call to be answered by exactly one
# tool response, so we rewrite, never append.
PENDING_TC = {}

def _messages(session_id):
    return list(CHATS.get(session_id, []))

def run_turn(session, user_text=None, emit=None, messages=None):
    emit = emit or (lambda name, payload: None)
    msgs = messages if messages is not None else _messages(session["session_id"])
    msgs = msgs[-40:]
    while msgs and msgs[0].get("role") == "tool":
        # The window can open onto an orphaned tool response (its assistant
        # message was trimmed). Drop it — a `tool` message must always sit
        # directly after the assistant message that carries its tool_call.
        msgs.pop(0)
    if user_text:
        msgs.append({
            "role": "user",
            "content": f"[{session.get('role')} {session.get('name')} | "
                    f"reference time "
                    f"{REFERENCE_NOW.strftime('%Y-%m-%d %H:%M')} IST]\n{user_text}",
        })

    pending = None
    for _ in range(MAX_TOOL_TURNS):
        full = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs
        estimate = sum(len(str(m.get("content", ""))) for m in full) // 4 + 2048
        if not budget.check(session.get("username"), estimate):
            return ("Your daily token budget is exhausted — this session can't continue until tomorrow. Ask an admin to raise the cap.", pending, msgs)
        try:
            resp = deepseek.chat(full, tools=tools.TOOLS_SCHEMA,
                                on_delta=lambda d: emit("text_delta", {"delta": d}))
        except Exception as e:
            return (f"Sorry — the model call failed: {e}", pending, msgs)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            budget.record(session.get("username"),
                        getattr(usage, "total_tokens", 0) or 0)

        msg = resp.choices[0].message
        calls = [c for c in (msg.tool_calls or [])
                if c.id and c.function and c.function.name]
        if not calls:
            return (msg.content or "I'm not sure how to help with that.",
                    pending, msgs)

        msgs.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls":[
                {"id": c.id, "type": "function",
                "function": {"name": c.function.name,
                            "arguments": c.function.arguments}}
            for c in calls
            ],
        })

        for c in calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                args = {}
                emit("tool_warning",
                    {"tool": name,
                    "detail": "arguments were not valid JSON; treated as {}"})
            args, arg_error = validate_args(name, args)
            if arg_error:
                emit("tool_warning", {"tool": name,
                                    "detail": f"invalid arguments: {arg_error}"})
                # A tool response is REQUIRED for every tool_call in the
                # block — never skip it (same contract that bit us before).
                msgs.append({"role": "tool", "tool_call_id": c.id,
                            "content": json.dumps(
                                {"status": "error",
                                "detail": f"invalid arguments: {arg_error}"})})
                continue
            emit("tool_start", {"tool": name, "args": args})
            result = tools.dispatch(name, session, args)
            emit("tool_result", {"tool": name, "result": result})
            msgs.append({"role": "tool", "tool_call_id": c.id,
                        "content": json.dumps(result, default=str)})
            if isinstance(result, dict) and result.get("requires_confirmation"):
                # Routing: the action sits in the pending store until the
                # role named in requires_role approves it via the
                # /api/pending panel. Register where this tool response
                # lives so a confirmation can rewrite it with the outcome.
                pending = pending or dict(result)
                pending.setdefault("action_type", name)
                PENDING_TC[result.get("action_id")] = {
                    "session_id": session["session_id"],
                    "tc_id": c.id,
                }

    return ("I hit my step limit for this request. Tell me how you'd like to "
            "continue.", pending, msgs)


def run_confirmation_continuation(session, action_id, approved,
                                emit=None, messages=None):
    emit = emit or (lambda name, payload: None)
    result = actions.confirm_action(session, action_id, approve=approved)
    if isinstance(result, dict) and result.get("status") == "already_handled":
        # main.py already executed/rejected this action before calling the
        # continuation — normalize so the model reports the real outcome
        # instead of a confusing "already_handled".
        result = {"status": result.get("current_status", "executed"),
                "action_id": action_id,
                }
    emit("tool_result", {"tool": "confirm_action", "result": result})
    msgs = messages if messages is not None else _messages(session["session_id"])

    # 1. Rewrite the PROPOSER's stored history (a different session than
    #    the one confirming) with the decision, so their next turn reports
    #    the real outcome instead of a stale "pending".
    reg = PENDING_TC.pop(action_id, None)
    if reg:
        proposer_msgs = CHATS.get(reg["session_id"])
        if proposer_msgs is not None:
            for m in proposer_msgs:
                if m.get("role") == "tool" and m.get("tool_call_id") == reg["tc_id"]:
                    m["content"] = json.dumps(result, default=str)
                    break

    # 2. Answer the confirming session. If the proposing block lives in
    #    these messages, rewrite it in place (1 tool_call -> 1 tool
    #    response); otherwise (cross-session approval) use a system note.
    replaced = False
    if reg:
        for m in msgs:
            if m.get("role") == "tool" and m.get("tool_call_id") == reg["tc_id"]:
                m["content"] = json.dumps(result, default=str)
                replaced = True
                break
    if not replaced:
        msgs.append({"role": "system",
                    "content": f"System: action {action_id} was "
                                f"{'APPROVED' if approved else 'REJECTED'} by the user. "
                                f"Result: {json.dumps(result, default=str)}. "
                                "Tell the user what happened and what comes next."})
    return run_turn(session, None, emit=emit, messages=msgs)
