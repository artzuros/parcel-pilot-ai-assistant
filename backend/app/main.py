# main.py -- FastAPI app: login, streaming chat, confirmation.
import json

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app import auth, ratelimit
from app.agent import loop
from app.config import REFERENCE_NOW
from app.data import db
from app.data import seed as seedmod
from app.executors import actions

@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    seedmod.seed_if_empty()
    yield


app = FastAPI(title="ParcelPilot Ops Assistant API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    session_id: str
    action_id: str
    approve: bool = True


def _sse(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@app.get("/api/health")
async def health():
    return {"status": "ok", "reference_now": REFERENCE_NOW.isoformat()}


@app.post("/api/login")
async def api_login(req: LoginRequest):
    r = auth.login(req.username, req.password)
    if r is None:
        return JSONResponse(status_code=401, content={"error": "invalid credentials"})
    return r


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    session = auth.get_session(req.session_id)
    if session is None:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    allowed, retry_after = ratelimit.check(req.session_id)
    if not allowed:
        return JSONResponse(status_code=429,
                            content={"detail": f"Rate limit exceeded. "
                                     f"Try again in {retry_after}s."})
    events = []

    def emit(name, payload):
        events.append(_sse(name, payload))

    final, pending, msgs = loop.run_turn(session, req.message, emit=emit)
    loop.CHATS[req.session_id] = msgs
    events.append(_sse("final", {"text": final,
                                "pending": pending.get("action_id") if pending else None}))

    async def stream():
        for ev in events:
            yield ev

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/confirm")
async def api_confirm(req: ConfirmRequest):
    session = auth.get_session(req.session_id)
    if session is None:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    result = actions.confirm_action(session, req.action_id, approve=req.approve)
    reply, next_pending = None, None
    if result["status"] in ("executed", "rejected"):
        msgs = loop._messages(req.session_id)
        final, pending, msgs = loop.run_confirmation_continuation(
            session, req.action_id, req.approve, messages=msgs)
        loop.CHATS[req.session_id] = msgs
        reply = final
        next_pending = pending if pending else None
    return {"result": result, "reply": reply, "next_pending": next_pending}
