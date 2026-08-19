# Nine agents, one goal, and the three bugs that were invisible from the outside

*I built Challenge Accepted for the All Things Agentic Hackathon, and I wrote this
piece for the purposes of entering that hackathon. It is about how the thing was
actually built — including the parts that were wrong for weeks.*

---

## The idea, in one paragraph

Every AI I asked for help with a goal gave me a plan. A good one. Twelve numbered
steps, sensibly ordered. I did none of them, because each step still needed something
I did not have: a spreadsheet model, a checklist, a comparison of four vendors, a
practice set.

The plan was never the missing piece. **The tools were.**

So Challenge Accepted does not stop at the plan. You name something you want to be
true that isn't yet. It interviews you until the goal is checkable by a stranger,
decomposes it into a dependency graph of two-hour tasks, and then — for every node —
asks *"what tool would make this step trivial?"*, writes that tool, runs it,
smoke-tests it, and attaches it to the node. Calculators, checklists, drills,
trackers, scripts, research briefs, small web apps.

Nine agents on Google ADK, Gemini 3.6 Flash and 3.5 Flash-Lite, Cloud Run, Firestore,
Vertex AI Memory Bank. It is live at <https://challengeaccepted.app>.

---

## The shape of the system

A root agent called Warden coordinates. Under it:

```
warden  (coordinator)
├── interviewer     mode=task          ACCEPT  clarifying questions -> charter
├── cartographer    mode=single_turn   MAP     charter -> goal graph DAG
├── forge           Sequential                 FORGE
│   ├── quartermaster   single_turn            per node: which tool is missing?
│   └── forge_loop      Loop
│       ├── dispatcher      custom BaseAgent   deterministic slot assignment
│       └── forge_workers   Parallel
│           └── toolwright_0..7                build + smoke-test, concurrently
├── coach           mode=task          CLIMB   one node at a time
│   └── referee     AgentTool                  evidence check + feedback
├── archivist       mode=single_turn   —       takes the notes
└── scout           AgentTool                  grounded search, on demand
```

Three decisions in there are worth naming, because each one could have gone the other
way:

**The Dispatcher is a custom `BaseAgent`, not an `LlmAgent`.** Assigning queue items to
worker slots is deterministic bookkeeping. A model call there would be slower, less
reliable, and untestable. Because it is not a model, it runs through a real ADK
`Runner` in the test suite with no API key — so the fan-out is the best-covered code
in the repo.

**Firestore is the source of truth, not session state.** ADK's `ParallelAgent` docs are
explicit that branch state is not automatically shared during execution. Session state
is only ever a per-slot inbox that exactly one worker reads.

**The tool taxonomy is closed.** Seven types, nothing else. Open-ended codegen is the
single biggest live-demo risk, and a failed build degrades to a plain checklist rather
than blocking the graph.

---

## The part I would tell another team first

Every real bug in this build was found by *running* the system. Not one was reachable
from a test that never calls a model. Ours passed, in full, while the deployed service
was silently building nothing.

Here is the one that cost the most.

**The money shot had never once run on the deployed service.** Not degraded — zero
tools, on every revision, while local runs built four to six every time and my own
README recorded that as verified. Deploy green, health green, graph drawn, journal
filling, the FORGE progress rail animating around `tools: []`.

Three bugs, stacked, each hiding the next:

1. `include_server_side_tool_invocations` is **required** on the Gemini Developer API
   and **raises** on Vertex AI. Local runs used an API key; the deploy used Vertex. The
   fix for one environment was the outage in the other. That took me from 0 tools to
   exactly 1 — always exactly 1, which is the shape of a bug, not a shortfall.

2. A worker's first model call returns an `executableCode` part carrying an `id`. ADK
   keeps it in history, the second call sends it back, and `google-genai` refuses to
   convert it. Workers run in an `asyncio.TaskGroup`, where **one failure cancels its
   siblings** — so the first worker to reach a second call killed the others
   mid-build. Hence exactly one tool, from whoever finished first.

3. With all of them surviving, it still built 4 of 7. `include_contents="none"` filters
   *session history*; it does not clear what the flow accumulates inside one
   invocation, and the `LoopAgent` re-runs the same worker instances. On iteration two a
   worker saw the tool it had already built and wrote prose about it in 1.6 seconds
   instead of building the new one — the exact failure that flag exists to prevent.

What made any of it findable was refusing to read silence as success. A worker that
does nothing and a worker with nothing to do produce identical output. So the phase now
narrates itself: dispatcher assignments, per-worker START/END with slot contents, and
every model call with its instruction size and content count.

---

## The bug that taught me to build the instrument first

Weeks later the shortfall came back. Five specs, two tools. Six specs, one tool. The
obvious suspect was worker parallelism, so I halved the batch. It got better. Three
times running.

That is exactly what a race looks like, and exactly what a *narrowed window* looks
like, and I could not tell them apart by staring at the code. So I stopped and wrote a
flow tracer: every agent entry logged with its ADK **branch**, every tool call, every
`transfer_to_agent`. The answer was in the first trace.

```
branch=cartographer@call_636196.forge_workers.toolwright_0   <- 5 specs, 2 tools
branch=cartographer@call_630649.forge_workers.toolwright_0   <- 6 specs, 1 tool
branch=forge_workers.toolwright_0                            <- 8 specs, 8 tools
```

FORGE was running *inside the Cartographer's frame.*

A `mode="single_turn"` sub-agent is not a transfer target in ADK — the parent gets it
as a **tool**, run in an isolated sub-branch. But ADK still offers that child its
parent as a transfer target, and when the child takes it, the Warden resumes *inside
the child's sub-branch* rather than after it. Everything the Warden starts from there —
the entire build phase — is parented to a tool call that is about to return. When it
does, FORGE dies underneath it: workers issue a second model call, never reach
`after_agent_callback`, the loop never dispatches another batch, and **nothing logs an
error.**

Two lines fixed it — `disallow_transfer_to_parent`, `disallow_transfer_to_peers`:
finish and return, like the tool it already was. Workers went back up to eight.

The lesson I keep re-learning: **a change that makes a symptom go away three times
running is still not a diagnosis.**

The same tracer caught the next one within a day. A run failed with 0 specs and 0
tools, and the trace told the whole story in two lines — `enter interviewer` at
22:25:23, `leave interviewer` at 22:25:35, and then nothing. No Warden, no
Cartographer, no FORGE, no error. The Interviewer's prompt ended with *"tell the user
in one sentence what you heard, and finish."* A `mode="task"` agent that emits text
instead of calling `finish_task` does not finish; ADK **pauses** and waits for a user
reply that is never coming. I had written the stall into the instructions myself, in
the most natural-sounding sentence in the file.

---

## Then I turned the same suspicion on my own tests

Having been burned three times by checks that were wrong about a working product, I
stopped trusting the suite and ran every check against the deployed service one at a
time, treating each failure as a claim to be proved rather than a bug to be fixed.

**Six were wrong about a working product.** One reported NO HANDOFF against a correct
handoff. One claimed tool state did not persist when it did. One graded the Referee's
*correct refusal* of weak evidence as a bug — twice, because my first fix hardcoded one
sport's idea of evidence. One encoded the access model from before invite keys existed.
Two hardcoded a worker count that had since changed.

**One had been blind since the day I added sign-in** — every request 401'd and the check
printed the traceback and moved on.

And they were hiding exactly one real defect: on any `/invite` error the button copied
a **keyless** link to the clipboard and said "Copied", so the failure mode of sharing a
party was handing someone a link guaranteed to 403.

A check that is wrong about a working product is worse than no check, because it spends
the attention you were saving for the real one.

---

## What I would keep

- **Instrumentation is not overhead you add after the bug.** It is what decides whether
  you get to have a diagnosis at all.
- **A request that cannot fail cannot teach you anything.** A session payload shaped one
  level too deep returned `200 OK` for weeks and produced three symptoms that looked
  like three different bugs.
- **Check whether the framework already solved it.** My worst outage was not a hard
  problem badly solved. It was an easy problem solved twice, where my version fought the
  library's. Ten minutes reading `starlette/middleware/base.py` would have saved all of
  it.
- **An agent that can claim a thing must be able to do the thing.** Warden once told a
  teammate *"I've recorded that into our shared group memory."* Nothing was written —
  the tool was on a different agent. It was the obviously right sentence to say, so the
  model said it.

Code, architecture diagram and the full write-up:
<https://github.com/banksythequantLab/challenge-accepted>
Live: <https://challengeaccepted.app>

*Written by Derek Soltis for the All Things Agentic Hackathon.*
