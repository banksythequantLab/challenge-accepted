# Devpost submission — Challenge Accepted

Paste-ready draft. Track: **Collaborative Partner**. Everything factual here was verified
by running it. Numbers marked *measured* came from instrumented live runs, not estimates.

---

## Inspiration

Every AI I asked for help with a goal gave me a plan. A good one. Twelve numbered steps,
sensibly ordered. I did none of them — because each step still needed something I didn't
have: a spreadsheet model, a checklist, a comparison of four vendors, a practice set.

The plan wasn't the missing piece. **The tools were.**

## What it does

You name something you want to be true that isn't yet. A team of nine agents:

1. **Interviews you** — 5–9 clarifying questions, and only questions whose answer would
   change the plan. It stops when the goal is checkable by a stranger.
2. **Draws a goal graph** — 8–20 micro-tasks as a dependency DAG, each ≤2 hours, each with
   a written acceptance criterion. Not a list. Parallel work stays parallel.
3. **Builds the tools** — for every node it asks *"what tool would make this step
   trivial?"* then writes it, runs it, smoke-tests it, and attaches it to the node.
   Calculators, checklists, drills, trackers, scripts, research briefs, mini-apps.
4. **Coaches you through it** — one ready step at a time, verifying evidence against the
   acceptance criterion, capturing thumbs up/down on every tool.

Everything learned lands in **goal-scoped group memory**. When a teammate opens the same
challenge, their Coach opens with what you discovered — attributed to you by name.

## How we built it

**Nine agents on Google ADK**, coordinated by a root agent called Warden:

```
warden  (coordinator, gemini-3.6-flash)
├── interviewer     mode=task          ACCEPT  clarifying questions -> charter
├── cartographer    mode=single_turn   MAP     charter -> goal graph DAG
├── forge           Sequential                 FORGE
│   ├── quartermaster   single_turn            per node: which tool is missing?
│   └── forge_loop      Loop
│       ├── dispatcher      custom BaseAgent   deterministic slot assignment
│       └── forge_workers   Parallel
│           └── toolwright_0..3                build + smoke-test, concurrently
├── coach           mode=task          CLIMB   one node at a time
│   └── referee     AgentTool                  evidence check + feedback
├── archivist       mode=single_turn   —       takes the notes
└── scout           AgentTool                  grounded search, on demand
```

**Stack:** Google ADK 2.6.3 · Gemini 3.6 Flash + 3.5 Flash-Lite · Cloud Run · Firestore ·
Vertex AI Memory Bank + Sessions · Agent Runtime code execution · FastAPI · Firebase Auth.

**Data sources:** user conversation, Google Search grounding (gated, not default-on), and
the group's own accumulated memory.

### Decisions worth defending

**Flash-only, deliberately.** The rules require "Gemini 3.5 or newer." As of August 2026
that is satisfied *only* by the 3.5/3.6 Flash family — **there is no Gemini 3.5 Pro**, and
`gemini-3.1-pro-preview` doesn't qualify despite being the flagship. So the architecture
compensates with structure rather than model power: two-pass decomposition, a closed
seven-type tool taxonomy, typed contracts between every phase. Bookkeeping agents run on
Flash-Lite at 5x lower input cost.

**The Dispatcher is a custom `BaseAgent`, not an `LlmAgent`.** Assigning queue items to
worker slots is deterministic bookkeeping; a model call there would be slower, less
reliable, and untestable. Because it isn't a model, it runs through a real ADK `Runner` in
the test suite with no API key — so the fan-out is the best-covered code in the repo.

**Firestore is the source of truth, not session state.** ADK's `ParallelAgent` docs are
explicit that branch state isn't automatically shared during execution. Session state is
only ever a per-slot inbox that exactly one worker reads.

**A closed tool taxonomy is scope control.** Seven types, nothing else. Open-ended codegen
is the single biggest live-demo risk; a failed build degrades to a plain checklist rather
than blocking the graph.

## Challenges we ran into

Every one of these was found by *running* the system. None were reachable from tests that
don't call a model — which is the actual lesson.

- **`400: enable tool_config.include_server_side_tool_invocations`.** A code executor is a
  server-side tool and Gemini won't mix it with client-side function calling unless that
  flag is set. Every Toolwright 400'd, and `ParallelAgent` buried it in an `ExceptionGroup`
  so it surfaced only as "unhandled errors in a TaskGroup."
- **An infinite delegation loop.** The Referee was a `task`-mode *sibling*. The Coach
  couldn't reach it, bounced to Warden, and Warden called `referee(...)` **25 times in one
  turn**, each returning nothing. Fixed by making it an `AgentTool` the Coach holds.
- **`AgentTool` agents must be `mode="chat"`** — an AgentTool runs its agent as a *root*,
  and ADK rejects a non-chat root. Scout had the identical defect sitting latent because
  nothing had ever invoked it.
- **Silent spec loss on re-entry.** The Dispatcher seeded its queue only when it was
  `None`; on a second FORGE entry the drained queue was treated as authoritative and every
  new ToolSpec was discarded — no error, no output, just nothing built.
- **Workers re-reported instead of idling.** Sharing a branch across loop iterations, a
  worker saw its own prior turn and wrote confident prose about a tool it had already
  built, with no `save_tool` call.
- **Re-planning appended instead of replacing.** A redraw after a blocker left 24 nodes —
  the old plan and the new one side by side.
- **Token accounting was wrong.** Thinking tokens bill as *output* on Gemini 3.x and live
  in `thoughts_token_count`, separate from `candidates_token_count`. Summing candidates
  alone under-reported cost by up to 3x.

## Accomplishments we're proud of

- An agent that writes a tool, **executes it, iterates until its own smoke test passes**,
  and hands it to a human who isn't a programmer.
- Group memory that actually crosses users: a teammate's first message is *"Derek found
  Cloud Run requires billing enabled and nobody on the team has admin, so we're using
  Vercel instead"* — attributed, unprompted.
- A blocker re-opening the interview and **redrawing the graph around the constraint**,
  then building new tools for the new plan.
- **52 tests**, including a regression test for every bug above.

## What we learned

Tests that never call a model cannot find the bugs that matter. Ours passed while the
system was silently building nothing. Every real defect came from a scripted live run with
full event logging — which is why `scripts/live_walk.py`, `live_climb.py` and
`live_group.py` sit in the repo alongside the unit tests.

The second lesson: when output is wrong, check whether the *data* the model needed even
exists before rewriting the prompt. Attribution failed not because the instruction was
weak but because the journal recorded `"Archivist"` as the actor — the user's name was
never stored anywhere.

## What's next

Challenge Packs — every completed graph is a template. Publish it, take 30%. Then per-node
assignment for teams, and a public gallery of generated tools.

## Business model

| Tier | Price | Included |
|---|---|---|
| Free | $0 | 1 challenge, 3 tools |
| Solo | $19/mo | 5 challenges, 40 tools/mo |
| Crew | $29/seat/mo | Unlimited, group memory, live graph |
| Forge | $99/mo | 400 tools, API, white-label |

*Measured*: one full challenge (12 nodes, 6 tools) = 243k prompt / 66k billed output
≈ **$0.86** at 3.6-flash rates. A challenge that hits a blocker and re-plans runs ~$1.90.
Break-even at $29/seat is ~34 challenges per user per month — comfortably above real usage.

## Known limitations, stated plainly

- `SequentialAgent` / `ParallelAgent` / `LoopAgent` are **deprecated in ADK 2.6.3** in
  favour of `Workflow`. We're on the deprecated path deliberately: the warning itself says
  "Workflow cannot yet be used as an LlmAgent sub-agent," and `mode="task"` agents are
  disabled inside graph-based workflows. Both ends of the migration are blocked.
- **Name collision:** a UK company ships a consumer app called Challenge Accepted. We own
  challengeaccepted.app; the mark is unresolved and would need clearing before any
  commercial launch.
- Group memory is goal-scoped and works across users, but there is no per-node assignment
  or presence yet — two people can pick up the same node.
