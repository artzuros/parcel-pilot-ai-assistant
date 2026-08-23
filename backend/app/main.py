# main.py -- FastAPI app: login, live-streaming chat, confirmation.
import asyncio
import json

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app import auth, ratelimit, budget
from app.agent import loop
from app.config import REFERENCE_NOW
from app.data import db, store
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

    async def stream():
        # The agent loop is synchronous and may make several model calls;
        # run it in a worker thread and ship every SSE event over a queue
        # the moment it is produced — that is what makes the reply stream.
        main_loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def emit(name, payload):
            main_loop.call_soon_threadsafe(queue.put_nowait, _sse(name, payload))

        def worker():
            try:
                final, pending, msgs = loop.run_turn(session, req.message, emit=emit)
                loop.CHATS[req.session_id] = msgs
                emit("final", {"text": final,
                               "pending": pending.get("action_id") if pending else None})
            except Exception as e:      # never leave the client hanging
                emit("final", {"text": f"Sorry — something went wrong: {e}",
                               "pending": None})
            finally:
                main_loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            await task

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


@app.get("/api/pending")
async def api_pending(session_id: str):
    session = auth.get_session(session_id)
    if session is None:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    approvals = [p for p in store.list_pending()
                 if auth.require_role(session, p["requires_role"])
                 or session.get("role") == "admin"]
    submissions = store.list_submissions(session_id)
    return {"approvals": approvals, "submissions": submissions}

@app.get("/api/budget")
async def api_budget(session_id: str):
    session = auth.get_session(session_id)
    if session is None:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return {"username": session["username"], **budget.stats(session["username"])}
