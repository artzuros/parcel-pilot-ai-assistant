import json

from app.agent import tools
from app.agent.system_prompt import SYSTEM_PROMPT
from app.config import REFERENCE_NOW
from app.executors import actions
from app.llm import deepseek

MAX_TOOL_TURNS = 6
CHATS = {}
# action_id -> the LLM tool_call id that proposed it. Needed when the user
# confirms/rejects so we can answer the original tool_call with a `tool`
# response (the API requires every tool_call to be answered).
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
        try:
            resp = deepseek.chat(full, tools=tools.TOOLS_SCHEMA)
        except Exception as e:
            return (f"Sorry — the model call failed: {e}", pending, msgs)
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
            emit("tool_start", {"tool": name, "args": args})
            result = tools.dispatch(name, session, args)
            emit("tool_result", {"tool": name, "result": result})
            msgs.append({"role": "tool", "tool_call_id": c.id,
                        "content": json.dumps(result, default=str)})
            if isinstance(result, dict) and result.get("requires_confirmation") \
                    and pending is None:
                pending = result
                PENDING_TC[result.get("action_id")] = c.id
                emit("confirmation_requested", {
                    "action_id": result.get("action_id"),
                    "action_type": result.get("action_type", name),
                    "requires_role": result.get("requires_role"),
                    "amount_inr": result.get("amount_inr"),
                    "message": result.get("message"),
                })
        if pending is not None:
            # End the turn here: the block above is complete (every tool_call
            # answered), the LLM was NOT called again, and no system note was
            # inserted. The user's decision arrives via the confirmation
            # endpoint and is appended as a tool response by the continuation.
            return (f"Awaiting your confirmation: {pending.get('action_type')} "
                    f"({pending.get('action_id')}) — requires "
                    f"{pending.get('requires_role')}. Approve or reject it.",
                    pending, msgs)
    return ("I hit my step limit for this request. Tell me how you'd like to "
            "continue.", pending, msgs)


def run_confirmation_continuation(session, action_id, approved,
                                  emit=None, messages=None):
    result = actions.confirm_action(session, action_id, approve=approved)
    emit("tool_result", {"tool": "confirm_action", "result": result})
    msgs = messages if messages is not None else _messages(session["session_id"])
    tc_id = PENDING_TC.pop(action_id, None)
    if tc_id:
        # Answer the original tool_call with the decision. This is a `tool`
        # message directly after the tool responses of the same block, so the
        # assistant->tool contract stays intact and the model can see the
        # outcome before replying.
        msgs.append({"role": "tool", "tool_call_id": tc_id,
                    "content": json.dumps(result, default=str)})
    else:
        # Fallback (e.g. server restarted between propose and confirm):
        # the tool_call id is gone, so explain the decision in a note.
        msgs.append({"role": "system",
                    "content": f"System: action {action_id} was "
                               f"{'APPROVED' if approved else 'REJECTED'} by the user. "
                               f"Result: {json.dumps(result, default=str)}. "
                               "Tell the user what happened and what comes next."})
    return run_turn(session, None, emit=emit, messages=msgs)
