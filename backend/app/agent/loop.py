import json

from app.agent import tools
from app.agent.system_prompt import SYSTEM_PROMPT
from app.config import REFERENCE_NOW
from app.llm import deepseek

MAX_TOOL_TURNS = 6
CHATS = {}

def _messages(session_id):
    return list(CHATS.get(session_id, []))

def run_turn(session, user_text=None, emit=None, messages=None):
    emit = emit or (lambda name, payload: None)
    msgs = messages if messages is not None else _messages(session["session_id"])
    msgs = msgs[-40:]
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
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
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
            if isinstance(result, dict) and result.get("requires_confirmation"):
                if pending is None:
                    pending = result
                    emit("confirmation_requested", {
                        "action_id": result.get("action_id"),
                        "action_type": result.get("action_type", name),
                        "requires_role": result.get("requires_role"),
                        "amount_inr": result.get("amount_inr"),
                        "message": result.get("message"),
                    })
            msgs.append({"role": "tool", "tool_call_id": c.id,
                        "content": json.dumps(result, default=str)})
        if pending is not None:
            msgs.append({"role": "system",
                        "content": "PAUSE: an action is awaiting user "
                                    "confirmation (see the tool result). "
                                    "Explain to the user, in a short reply, "
                                    "exactly what needs approval. Do not "
                                    "propose further state-changing actions "
                                    "until the user responds."})
    return ("I hit my step limit for this request. Tell me how you'd like to "
            "continue.", pending, msgs)
    

def run_confirmation_continuation(session, action_id, approved,
                                  emit=None, messages=None):
    if approved:
        note = f"System: action {action_id} was APPROVED by the user. " \
               "Proceed with the task; take the next step if any remains."
    else:
        note = f"System: action {action_id} was REJECTED by the user. " \
               "Do not perform it; adjust and tell the user what happens next."
    msgs = messages if messages is not None else _messages(session["session_id"])
    msgs.append({"role": "system", "content": note})
    return run_turn(session, None, emit=emit, messages=msgs)