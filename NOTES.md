# NOTES — architecture decisions & product notes

## Architecture decisions worth explaining

**1. In-memory + single-worker design.** The approval registry (which tool call
a pending action maps back to, for history rewriting), session state, rate
limits and token budgets all live in memory, so the service must run as a
single uvicorn worker. This is a deliberate trade-off for a demo-scale
deployment (t3.micro): the systemd unit enforces one worker, and scaling up
would mean moving these registries into SQLite/Redis. The actions themselves
are already durable in SQLite with an audit log.

**2. Retrieval is deterministic, not semantic.** `rank_bm25` over chunked text
with authority-aware weighting (agreements > SOP > policy > product docs,
deprecated = 0.25) — no embedding model, no external retrieval API. For this
data pack (six documents, one store) it is reliable, cheap, and every answer
can name its source. The `effective`/`updated` metadata is surfaced to the
model so it can state *when* a policy took effect, which is what "freshness"
means for a policy document.

**3. The model never computes policy numbers.** SLA deadlines, cancellation
fees and credit amounts are all produced by the policy engine and reported
verbatim. The prompt forbids arithmetic; the engine is unit-tested (92 tests).
This is the single most important reliability property — the LLM's role is
language and tool orchestration, not calculation.

**4. Confirmations are rewrites, not appends.** When an approver confirms an
action, the *proposer's* chat history is rewritten in place so the original
tool call shows `executed` — the model can't drift from reality in later
turns. Decisions are also audit-logged with actor + payload.

**5. Reference-time convention.** The data pack is a snapshot; all time
arithmetic uses `2026-08-16 11:00 IST`. Wall-clock is used only for TTLs,
rate limiting and budget. This keeps answers consistent with the pack no
matter when the demo runs.

## Product note — the trust problem (Problem 2)

The core product risk for a support chatbot is **trust**: support staff will
stop using a bot that states a wrong SLA, promises a credit that isn't owed,
or — worse — executes an action nobody approved. The design attacks this at
four layers:

1. **Source authority** — answers must name their source; agreements override
   policy; deprecated documents are surfaced but never applied.
2. **Computational honesty** — all numbers come from the policy engine, not
   the model; the engine is unit-tested.
3. **The confirmation gate** — no state change without (a) the user confirming
   and (b) a role-appropriate approver confirming. The data layer enforces
   who may propose, who may approve, and what they may see.
4. **History rewriting** — the conversation itself is kept truthful: a
   proposed action that got rejected shows as rejected, and the model cannot
   later claim it "was done" because the tool result says pending/executed.

**What I'd build next** (beyond scope of this assignment):

- Semantic retrieval (embeddings) as a complement to BM25, with citation
  grounding — improves recall on paraphrased questions.
- Per-account spend tracking beyond the monthly credit cap (the cap is
  enforced at propose time; a standing budget dashboard would close the
  loop).
- Escalation from bot to human with the full conversation context
  (ParcelPilot's "escalate to a manager" is currently an internal action,
  not a hand-off).
- Evaluation harness: golden Q&A set + LLM-as-judge scoring, so policy
  changes can be regression-tested before deployment.

## AI tooling statement

Development was AI-assisted: Claude Code (Anthropic's CLI) was used to
implement and iterate on the codebase under the author's direction —
including writing most of the backend, the frontend, and this documentation.
All code was reviewed, all 92 unit tests run and passing, and the end-to-end
flows were smoke-tested against the live deployment. The author takes full
responsibility for the design decisions and the code.
