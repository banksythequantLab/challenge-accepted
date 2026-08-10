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
| Verified live | 8-turn interview -> charter saved -> 10-node DAG -> 4 tools built, smoke-tested and persisted |
| Verified live | Warden -> `forge` transfer via `transfer_to_agent`; Quartermaster `output_schema`; parallel Toolwrights executing real code |
| Verified | 11 tests pass against a real ADK `Runner`; FastAPI boots, `/healthz` 200 |
| Measured | One full challenge = **194k prompt / 20k output tokens, ~$0.44** at 3.6-flash rates |
| Suspect | Exactly 4 tools for 10 nodes = `FORGE_WORKERS`. The LoopAgent may not be draining the queue past batch one. **Verify before trusting the fan-out.** |
| Not run | CLIMB phase (Coach/Referee) end to end; group memory across two users |
| Not built | Next.js front end, React Flow graph, Firebase Auth, Cloud Run deploy |

Reproduce with `python scripts\live_walk.py` (costs ~$0.44).

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
