# ParcelPilot Ops Assistant

An NL support chatbot for ParcelPilot (a fictional B2B logistics provider), built
for the CalQuity AI Engineer take-home assignment. It answers support questions
exclusively from the supplied data pack (policies, SOPs, agreements, and a
mock accounts/orders/tickets store), computes policy numbers itself, and routes
every state-changing action through an explicit user confirmation gate.

## Stack

| Layer | Choice | Why |
|---|---|---|
| LLM | DeepSeek via the OpenAI SDK (`deepseek-v4-flash`, streamed) | supplied budget; streaming gives a live typing feel |
| API | FastAPI + uvicorn (single worker) | one in-memory approval-registry, sessions and budgets |
| Retrieval | `rank_bm25` over chunked extracted PDF text | deterministic, offline, no embedding API cost |
| Store | SQLite (stdlib) | the mock accounts/orders/tickets/actions/credits store |
| Auth | mock login; **role checks enforced in the data layer** | access control is a data-layer concern, not just UI |
| Frontend | static HTML/CSS/JS (no framework), markdown rendered by hand | zero build step; served from Cloudflare Pages |
| Deploy | AWS EC2 t3.micro + Cloudflare Tunnel + Cloudflare Pages | outbound-only ingress; no open ports except SSH |

## How to run locally

Backend (needs Python 3.10+):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # or your conda env
pip install -r requirements.txt
export DEEPSEEK_API_KEY=sk-...                      # required to chat
uvicorn app.main:app --reload --port 8000
```

Frontend — open `frontend/index.html` (it talks to `http://localhost:8000`
when opened locally, or open it via a static server):

```bash
cd frontend && python3 -m http.server 8001   # then open http://localhost:8001
```

Tests (92 unit tests, no API key needed):

```bash
cd backend && python -m pytest
```

## Demo logins

The auth is mocked for the demo; **role checks are enforced by the backend data
layer** (a session may only read data its role permits and only confirm
actions its role is allowed to approve).

| User | Role | Password |
|---|---|---|
| aisha | support_agent | parcelpilot |
| rohan | manager | parcelpilot |
| neha | admin | parcelpilot |

## What it can do

- **Document Q&A with source authority** — retrieves from the data pack
  (support policy v3 current, v2 **DEPRECATED**, Cancellation & Service Credit
  SOP v4, product guide, Northstar & LumenWorks agreements). Every answer names
  its source; agreements beat policy; deprecated documents are flagged, never
  applied. Search weights authority and the `effective` date so v3 outranks v2.
- **Structured lookup & calculation** — accounts, orders, tickets, SLA
  deadlines (business-hours aware, per-agreement), cancellation fees,
  service-credit amounts. The model never computes policy numbers itself; it
  calls the matching tool and reports the result verbatim.
- **State-changing actions behind a confirmation gate** — escalate a ticket,
  update a ticket, create a follow-up task, propose a service credit. Every
  proposal is stored as `pending`, the user is asked to confirm, and a
  higher-role approver must approve before anything is executed. All decisions
  are audit-logged; the monthly credit cap is enforced at propose time.

Tools: `doc_search`, `get_account`, `get_orders`, `get_tickets`,
`sla_deadline`, `cancellation_check`, `credit_check`, `classify_severity`,
`escalate_ticket`, `update_ticket`, `create_followup_task`, `propose_credit`,
`pending_approvals`.

## Time convention

The data pack is a snapshot: **the reference "now" is 2026-08-16 11:00 IST**.
All time arithmetic (SLA deadlines, cancellation windows, credit thresholds)
uses that reference time; the wall clock is only used for confirmation TTLs,
rate limiting and token budgets.

## Architecture

```
frontend/        static chat UI (login, chat, live tool feed, approvals panel)
backend/app/
  agent/         system prompt, tool schemas, agent loop (SSE streaming)
  executors/     doc_search, data_lookup, calc (SLA/fees/credits), actions
                 (proposals + confirmation gate), policy_core (policy engine)
  retrieval/     chunking + BM25 index over data/extracted_text, docs_meta.json
  data/          SQLite schema, seed data, auth, pending-action store
  llm/           DeepSeek client (streamed completions, tool-call reassembly)
  main.py        FastAPI app: /api/chat (SSE), /api/confirm, /api/pending,
                 /api/budget, /api/login, /api/health
deploy/          EC2 setup.sh + deploy.sh + systemd unit
docs-processing/ extract_pdfs.py (PDF -> text), build_seed.py (JSON -> SQLite)
```

Approval flow: anyone submits a state-changing action → it lands in the
`actions` table as `pending` → the approver's panel polls `/api/pending` →
`POST /api/confirm` → the proposer's chat history is rewritten in place so the
conversation shows the action as executed/rejected, and the decision is
audit-logged. A re-proposal supersedes the earlier pending one (no duplicate
cards), and the confirm is an atomic claim — a credit can never be issued
twice.

## Deploying

One-time EC2 setup (Amazon Linux 2023): `deploy/setup.sh` installs deps, the
Cloudflare Tunnel client, clones the repo and installs the systemd service.
The API binds to `127.0.0.1:8000`; the Cloudflare Tunnel is the only way in —
no public ports. Updates: `deploy/deploy.sh` (pull + restart), or:

```bash
ssh ec2-user@<host> 'cd ~/parcel-pilot-ai-assistant && ./deploy/deploy.sh'
```

Secrets live in `/etc/parcelpilot.env` (`DEEPSEEK_API_KEY=...`, mode 600) —
never on the frontend or in the repo.

- API (tunneled): https://parcel-pilot-api.pranav-bansal.com
- Frontend: Cloudflare Pages

## Repository layout

- `data/` — the supplied data pack: PDFs, extracted text, seed JSON
- `backend/tests/` — 92 unit tests (policy engine, retrieval, data layer,
  confirmation gate, auth/roles, budget, rate limiting, agent loop)

See `NOTES.md` for architecture decisions and product notes.
