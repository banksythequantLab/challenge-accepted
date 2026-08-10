# Challenge Accepted

**Every other AI gives you a plan. This one builds you the tools.**

You name something you want to be true that isn't yet. A team of agents interviews you
until the goal is actually specific, draws it as a dependency graph of micro-tasks, then
asks a question nothing else in the category asks -- *what tool would make this step
trivial?* -- and builds it. Everything they learn lands in a shared memory that every
agent and every teammate reads from.

Built for the [All Things Agentic hackathon](https://allthingsagentichackathon.devpost.com/),
**Collaborative Partner** track. Deadline: Aug 31 2026, 5pm PDT.

---

## Status

**v0.2 -- full ACCEPT -> MAP -> FORGE pipeline verified against live Gemini.**

| | |
|---|---|
| Verified live | 8-turn interview -> charter saved -> 12-node DAG -> 6 tools built, smoke-tested and persisted |
| Verified live | Warden -> `forge` transfer via `transfer_to_agent`; Quartermaster `output_schema`; parallel Toolwrights executing real code |
| Verified | 24 tests pass against a real ADK `Runner`; FastAPI boots, `/healthz` 200 |
| Measured | One full challenge (12 nodes, 6 tools) = **243k prompt / 66k billed output, ~$0.86**. Break-even at $29/seat ≈ **34 challenges/user/month** |
| Fixed | The "exactly 4 tools" ceiling. Two causes, both live-only. See Known issues. |
| Verified live | CLIMB end to end: node closed on evidence, feedback captured with reason, blocker -> group fact -> interview re-opened -> graph redrawn around the constraint |
| Not run | Group memory across **two** users (single-user group memory works) |
| Not built | Next.js front end, React Flow graph, Firebase Auth, Cloud Run deploy |

Reproduce with `python scripts\live_walk.py` (costs ~$0.86, prints full token accounting).

**Token accounting gotcha:** thinking tokens bill as *output* on Gemini 3.x and are
reported in `thoughts_token_count`, separate from `candidates_token_count`. Summing
candidates alone under-reported cost by up to 3x -- measured 725 thinking vs 251 visible
on one short call. `live_walk.py` now sums both; anything estimating cost must too.

Run `pytest` to see exactly what is and isn't covered.

---

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env      # add GOOGLE_API_KEY from aistudio.google.com
pytest                      # 10 tests, no API key needed

adk web                     # dev UI at http://localhost:8000
python main.py              # or FastAPI on :8080, health at /healthz
```

With no `GOOGLE_CLOUD_PROJECT` set, the store falls back to an in-process dict, so
everything runs locally with zero GCP setup.

---

## Architecture

```
warden  (coordinator, gemini-3.6-flash)
+-- interviewer     mode=task          ACCEPT  clarifying questions -> charter
+-- cartographer    mode=single_turn   MAP     charter -> goal graph DAG
+-- forge           Sequential                 FORGE
|   +-- quartermaster   single_turn            per node: which tool is missing?
|   +-- forge_loop      Loop
|       +-- dispatcher      custom BaseAgent   deterministic slot assignment
|       +-- forge_workers   Parallel
|           +-- toolwright_0..3                build + smoke-test, concurrently
+-- coach           mode=task          CLIMB   one node at a time
+-- referee         mode=task          CLIMB   evidence check + feedback capture
+-- archivist       mode=single_turn   --      takes the notes (cross-cutting)
+-- scout           AgentTool                  grounded search, on demand
```

### Design decisions worth defending

**Flash-only, deliberately.** The rules require *"Gemini 3.5 or newer."* As of Aug 2026
that is satisfied only by `gemini-3.6-flash`, `gemini-3.5-flash` and
`gemini-3.5-flash-lite` -- **there is no Gemini 3.5 Pro**, and `gemini-3.1-pro-preview`
does not qualify despite being the flagship. So the architecture compensates for Flash
with structure rather than model power: two-pass decomposition, closed tool taxonomy,
typed hand-offs. Bookkeeping agents (Archivist, Referee) run on Flash-Lite at 5x lower
input cost.

**Dispatcher is a custom `BaseAgent`, not an `LlmAgent`.** Assigning queue items to
worker slots is deterministic bookkeeping. Paying for a model call would be slower, less
reliable, and untestable. As written it runs through a real `Runner` in the test suite
with no API key -- which is why fan-out is the best-covered part of the codebase.

**Firestore is the source of truth, not session state.** ADK's `ParallelAgent` docs are
explicit that branch state is *not* automatically shared during execution, and recommend
locks or external state management for concurrent writes. `services/store.py` is that
external state. Session state is only ever a per-slot inbox that exactly one worker reads.

**Scout is wrapped as an `AgentTool`.** A built-in tool such as `google_search` excludes
every other tool on the same agent, so Scout lives alone and is reached through
`AgentTool`. Toolwright likewise carries a `code_executor` and a minimal tool surface.

**Coach is `mode="task"`, not `chat`.** Chat mode returns to the parent only via an
explicit `transfer_to_agent` and is not parallel-safe; task mode auto-returns via
`finish_task()`, which is what makes the CLIMB -> ACCEPT re-open path work.

**The closed tool taxonomy is scope control.** Quartermaster may request exactly seven
types -- `calculator`, `checklist`, `research_brief`, `drill`, `tracker`, `script`,
`mini_app`. Open-ended codegen is the single biggest live-demo risk. Anything that
doesn't fit gets rejected back for reshaping, and a failed build degrades to a plain
checklist rather than blocking the graph.

---

## Known issues

### Fixed: CLIMB deadlocked, then dropped feedback, then duplicated everything

CLIMB is half the track brief ("guide the user step-by-step... capture feedback") and
had never run. Four defects, in the order they surfaced:

**1. Infinite delegation loop.** The Referee was a `mode="task"` sibling of the Coach
under Warden. The Coach was told to "transfer to referee" -- unreachable from a sibling
-- so it transferred up to Warden, whose instruction never mentioned a Referee. Warden
improvised: `referee(...)` **25 times in one turn**, each returning nothing, each
failure prompting another attempt. Fixed by making the Referee an `AgentTool` the Coach
holds, plus an explicit Warden rule never to retry a silent delegation.

**2. An AgentTool's agent must be `mode="chat"`.** An AgentTool runs its agent as a
*root* agent, and ADK rejects a non-chat root. The Referee was `single_turn` and raised
the moment it was called. **Scout had the identical defect sitting latent** -- it had
simply never been invoked in any run. `tests/test_agent_wiring.py` now guards both.

**3. Feedback went to the Referee and was lost.** "Thumbs up on that checklist" was
routed as completion evidence; the Referee judged it against an acceptance criterion,
returned NOT_MET, and `record_feedback` never fired. The Coach now owns `record_feedback`
and `remember_group_fact` directly, with explicit turn-routing rules.

**4. Re-planning appended instead of replacing.** After the blocker the graph was
correctly redrawn -- and the challenge ended with **24 nodes**, the old plan and the new
one side by side. `save_goal_graph` now marks dropped nodes `superseded`; anything
already `done` keeps its status and evidence.

**5. Group facts duplicated.** One constraint was stored three times because three
agents phrased it three ways. Exact-string dedup missed all of it. Now compared on
normalised content-word overlap. `tests/test_replan.py` uses the three real phrasings.

Worth keeping: the Referee's *strictness* is not a bug. It rejected "I saved a
screenshot" against a criterion asking for logs across three sample goals. That is the
product working.

### Fixed: the "exactly 4 tools" ceiling

Two consecutive live runs each produced exactly 4 tools, and `FORGE_WORKERS` is 4. Two
independent causes, neither reachable from a test that does not call a model:

**1. Stale queue across a second FORGE entry.** The Dispatcher seeded its queue only
when `forge_queue is None`. Warden delegates to `forge` more than once per session, and
on the second entry the drained `[]` from the first was treated as authoritative -- so
the Dispatcher escalated immediately and *silently discarded every new ToolSpec*. The
run simply builds nothing and says nothing. Now the queue reseeds whenever the spec set
changes, keyed on a fingerprint of the node ids. Covered by `tests/test_forge_reentry.py`.

**2. Workers re-reported instead of idling.** A worker keeps the same branch across loop
iterations, so it saw its own previous turn. On iterations where its slot was empty it
wrote confident prose re-summarising the tool it had already built -- no `save_tool`
call, pure wasted tokens, and misleading logs. Fixed with `include_contents="none"` so a
worker sees only its instruction plus the injected slot.

After both fixes: 12 nodes -> 6 tools, and `save_tool` calls now equal tools persisted.

Worth knowing for the writeup: the loop itself was never broken. `tests/test_forge_loop.py`
proved it drains 10 specs in batches of 4/4/2 before either fix landed. The temptation
was to "fix" the loop; the evidence said not to.


**`SequentialAgent` / `ParallelAgent` / `LoopAgent` are deprecated in ADK 2.6.3**, in
favour of the new `google.adk.workflow.Workflow`. We are on the deprecated path on
purpose, because the migration is currently blocked from both ends:

- the deprecation warning itself says *"Workflow cannot yet be used as an LlmAgent
  sub-agent"* -- and `forge` must be a sub-agent of `warden`;
- `mode="task"` agents (Interviewer, Coach, Referee) are **disabled inside graph-based
  workflows** in ADK Python v2.x.

Revisit when ADK lifts either restriction. Flag this in the submission writeup rather
than hiding it -- it reads as someone who understood the framework.

**Warden reaches `forge` via `transfer_to_agent`, not an auto-injected delegation tool.**
ADK auto-injects delegation tools only for `task`/`single_turn` `LlmAgent` sub-agents;
workflow agents are reached through the transfer tool that `AutoFlow` adds at request
time. Confirmed present (`_AgentTransferLlmRequestProcessor` is in the flow), but this
path is **not covered by a test** and should be the first thing checked once a key is in.

---

## Layout

```
challenge_accepted/
  agent.py            root_agent (Warden)
  config.py           model tiers, GCP wiring, behaviour knobs
  schemas.py          typed contracts between phases
  prompts.py          all nine instructions, side by side
  sub_agents/         one file per agent; forge.py holds the fan-out pipeline
  services/
    store.py          Firestore repository, in-memory fallback
    tools.py          ADK FunctionTools over the store
main.py               Cloud Run entrypoint via get_fast_api_app
tests/                10 tests, no API key required
docs/                 plan + architecture diagram
```

## Next

1. Add a `GOOGLE_API_KEY` and run `adk web` -- the prompts have never faced a model.
2. Walk one real challenge end to end; instrument token counts from the first run.
3. Verify the Warden -> `forge` transfer with a live key.
4. Front end: Next.js + React Flow + Firebase Auth, Firestore listeners for the live graph.
