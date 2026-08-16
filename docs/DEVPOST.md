# Devpost submission — Challenge Accepted

Paste-ready draft. Track: **Collaborative Partner**. Everything factual here was verified
by running it. Numbers marked *measured* came from instrumented live runs, not estimates.

**Try it:** https://challengeaccepted.app — sign in with Google · health:
https://challengeaccepted.app/api/healthz (states the auth mode out loud, so "is it
actually locked?" is answerable without taking our word for it)

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

You sign in with Google, and the party roster shows the people on it rather than machine
ids. Dark and light themes; the app follows your machine and remembers if you disagree.

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
Vertex AI Memory Bank on Agent Engine · FastAPI.

Three things that line does *not* claim, because they are not true and a stack list is
the easiest place in a submission to lie by omission:

- **Sessions are not Agent Engine sessions.** They run on a `BaseSessionService` we
  wrote against Firestore, registered under a `firestore://` scheme through ADK's own
  service registry. That was a deliberate build, not a fallback — see *Challenges*.
- **Code execution is ADK's `BuiltInCodeExecutor`**, model-side, not a persistent Agent
  Runtime sandbox. One env var swaps it; the env var is unset.
- **Sign-in is Google only.** Firebase Authentication, verified server-side with the
  Admin SDK. There is no email/password tier and no anonymous tier — an anonymous uid
  is the same fiction we removed, wearing a server-issued costume.

### Identity, and what it actually protects

Until late in the build, identity was a random string the browser generated and the
server believed. The roster listed `u_9a3d0a`; a challenge belonged to whichever group
the client claimed; anyone who guessed a challenge id could read someone else's plan.

Adding a login is the easy half. The half that matters is that **ADK takes the user id
from the URL** (`POST /apps/{app}/users/{user_id}/sessions`) **and from the `/run_sse`
body** — and those ids are what `save_charter` files a challenge under. Verifying a
token and then letting the client keep naming itself would be theatre: you could sign in
as yourself and create a challenge owned by someone else, with a token that verifies
perfectly. So the gate refuses any request whose stated user is not the verified one,
and there is a test for each path.

Reading a challenge requires **membership of its party**, not possession of its id. An
invite link is an invitation to *join* — sign in, join, then see — and joining is a
button you press, not something a URL does to you.

The ADK dev UI is switched off whenever auth is on. It is an unauthenticated console
that can run agents as any user id you type into it, which on a public URL is a free
Gemini endpoint on our bill. A gate with a second door beside it is a decoration.

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
- **A request that could not fail, and therefore told us nothing.** The dashboard created
  its ADK session by posting `{"state": {...}}` to `POST .../sessions/{id}`. That endpoint
  declares `state` as a *bare body parameter* — the whole body **is** the state — so every
  session was created with state equal to `{"state": {...}}`, one level too deep. FastAPI
  returned `200 OK`. Nothing logged. Three unrelated-looking symptoms followed from it:
  every challenge created from the dashboard was owned by `anon` in group `grp_anon`, a
  teammate opening an invite link resolved to their own private group, and the Warden
  re-interviewed people about a goal already drawn on the screen behind the chat panel.
  Found only by driving **two real browsers at once**.
- **An agent claiming a write it had no tool to perform.** Warden answered a teammate with
  *"I've recorded that into our shared group memory."* Nothing was written —
  `remember_group_fact` was on Archivist and Coach, not on Warden. It was the obviously
  right sentence to say, so the model said it. An agent that can claim a thing must be
  able to do the thing.
- **A rule that lost an argument with seven other rules.** "A joining teammate does not get
  interviewed" sat eighth in a numbered list and was ignored live. Rewritten as an ADK
  `InstructionProvider` that restates the in-flight challenge — title, outcome, progress —
  as *fact* each turn. Rules compete. Facts don't.
- **A feedback button that wrote to a table nobody read.** `record_feedback` had no reader
  anywhere in the codebase, so "tell it what didn't work and the next one is different" was
  false. It had gone unnoticed because the reason box was a native `window.prompt()`, which
  blocks the page and every browser check driving it. An untestable control rots.
- **The money shot had never once run on the deployed service.** Not degraded — zero
  tools, on every revision, while local runs built four to six every time and our own
  README recorded that as verified. Three bugs, stacked, each hiding the next, and every
  one of them invisible from outside: deploy green, health green, graph drawn, journal
  filling, FORGE rail animating around `tools: []`.

  **(1)** `include_server_side_tool_invocations` is *required* on the Gemini Developer
  API and **raises** on Vertex. Local runs use an API key; the deploy uses Vertex. The
  fix for one environment was the outage in the other. That took us from 0 tools to
  exactly 1 — always exactly 1, which is the shape of a bug, not a shortfall.

  **(2)** A worker's first model call returns an `executableCode` part carrying an `id`.
  ADK keeps it in history; the second call sends it back; `google-genai` refuses to
  convert it. And workers run in an `asyncio.TaskGroup`, where **one failure cancels its
  siblings** — so the first worker to reach a second call killed the other three
  mid-build. Hence exactly one tool, from whoever finished first.

  **(3)** With all four surviving, it still built 4 of 7. `include_contents="none"`
  filters *session history*; it does not clear what the flow accumulates inside one
  invocation, and the LoopAgent re-runs the same worker instances. On iteration two the
  worker saw the tool it had already built and wrote prose about it in 1.6 seconds
  instead of building the new one — the exact failure that flag was added to prevent.

  Now **6 specs asked, 6 tools built**, on the deployed service. What made any of it
  findable was refusing to read silence as success: a worker that does nothing and a
  worker with nothing to do produce identical output, so the phase now narrates itself —
  dispatcher assignments, per-worker START/END with slot contents, and every model call
  with its instruction size and content count. One env var, off by default.

- **Three unrelated subsystems riding on one boolean.** `use_vertex()` gated sessions,
  memory *and* Cloud Trace. Switching on Memory Bank would therefore also have moved
  every conversation off our Firestore session service onto Agent Engine — nothing would
  have errored; sessions would just have been served by code with no coverage in this
  repo. Splitting it exposed a second trap by reading ADK's source: given a *bare* engine
  id, its `agentengine://` factory reads the region from `GOOGLE_CLOUD_LOCATION`, which
  we set to `global` because Gemini 3.x is served from the global endpoint. An Agent
  Engine is regional. That would have built a Memory Bank client aimed at a region the
  engine doesn't live in — and failed **silently**, because both ends swallow their
  errors by design, so the app would have run perfectly and remembered nothing. We emit
  the full resource path instead. The third only surfaced on deploy: `trace_to_cloud`
  turned on too, and its OpenTelemetry exporter had never been in `requirements.txt`, so
  the container died at import before binding the port. The previous revision kept
  serving and the deploy script's explicit `$LASTEXITCODE` check reported the failure
  rather than printing "Deployed" over it. Three subsystems, found three different ways:
  reading the diff, reading the vendor's source, reading a crash log.

- **A workaround for a problem the framework had already solved, which took the site
  down.** To check that `/run_sse` was not being run as somebody else, the auth gate has
  to read the request body. Assuming that consuming it would starve the route
  downstream, we hand-wrote a replacement `receive()` that hands the body back — on
  *every* call. `/run_sse` answers with a streaming response, and Starlette sits in a
  loop on `receive()` waiting for the client to disconnect. It got the body a second
  time and raised `RuntimeError: Unexpected message received: http.request` **after the
  HTTP 200 had already gone out**. Every agent run on the site died at 46 ms with zero
  events and no error the user could see: you typed a message and nothing happened.
  Starlette caches and replays the body itself; the fix was deleting our code. The unit
  test had passed because it exercised a *JSON* route, and a JSON route never listens
  for a disconnect — it asserted the mechanism we had built rather than the thing the
  product does.

- **Auth silently turned every invite link into a blank page.** One line decided which
  quest a browser lands on: `if (!known(challengeId)) challengeId = null;`. Correct
  while `/challenges` returned every quest in the store — and the moment the list became
  private, a teammate opening an invite link had the id cleared on load. They saw "no
  quest yet", no map, and no offer to join, because the request that triggers the join
  prompt was never made. The entire collaborative premise, dead, with nothing anywhere
  saying so. Found by two signed-in browsers, not by reasoning about the diff.

- **Three test failures that were the test's fault, not the product's.** A browser
  walkthrough reported `nodes: 0` and "FORGE produced nothing" against a service that
  had just built seven tools. It was waiting for a spinner the app removes when a
  response *starts* streaming, then screenshotting a run still in flight. A second
  check asserted on a dashboard shape it had invented. A third asserted that no tool
  could be opened from a detail pane it had never opened. Each one looked like a product
  bug and cost real time — the discipline that eventually pays is asking *"is the
  measurement wrong?"* before rewriting the thing being measured.

## Accomplishments we're proud of

- An agent that writes a tool, **executes it, iterates until its own smoke test passes**,
  and hands it to a human who isn't a programmer.
- Group memory that actually crosses users: a teammate's first message is *"Derek found
  Cloud Run requires billing enabled and nobody on the team has admin, so we're using
  Vercel instead"* — attributed, unprompted.
- A blocker re-opening the interview and **redrawing the graph around the constraint**,
  then building new tools for the new plan.
- A second person opening an invite link **inherits the party's knowledge and adds to
  it**, with the header roster going 1 → 2 on the first person's screen while they sit
  still. Driven through two separate browser contexts, not two tabs — tabs share
  `localStorage` and would have let three real bugs pass.
- **Memory that survives the conversation it was told in.** A brand-new session — no
  `challenge_id`, no `group_id`, nothing in state — answered *"what do you already know
  about me?"* with a constraint the user had mentioned during a *previous* challenge.
  Vertex AI Memory Bank is read by ADK's `preload_memory` on Warden and the Interviewer
  and written by `save_charter` and `complete_node`. `scripts\check_memory.py` proves it
  end to end; `scripts\check_memory_bank.py` sits underneath and round-trips the service
  directly, so a failure tells you whether the infrastructure or the prompt broke.
- **The party notebook fills itself from the interview.** `remember_group_fact` only
  fires on a *returning* turn, so a freshly planned challenge greeted its first teammate
  with "Nothing learned yet" while the charter it had just written held the deadline,
  the constraints and everything already tried. Those now seed the notebook at
  `save_charter` — in code, not by asking an agent, because a prompt that says "also
  record these" is a prompt that can claim it did and not have. Empty form answers are
  filtered: "None (running solo)" is not a shared discovery.
- **Dark and light, both measured.** Every colour is a token, including the ones baked
  into the SVG the quest map emits — left alone, the centrepiece would have stayed
  near-black on a white page. `check_theme.py` reads the *rendered* luminance of every
  painted surface and fails if one stayed dark; `check_a11y.py` runs contrast in both
  themes (worst: 5.60:1 dark, 4.86:1 light, against a 4.5:1 floor).
- **153 tests plus a live-check suite that signs in**, including a regression test for
  every bug above. The checks click the actual controls and read the clipboard, the
  iframe and the resulting prompt string back — `check_feedback.py` follows a
  thumbs-down all the way into the Quartermaster's instruction, because "the loop is
  closed" and "the loop is open" look identical from outside.
- **Locking the doors did not cost us the ability to test them.** Auth made every live
  check return 401, which would have left the deployed service verifiable only by hand —
  exactly the gap that let the streaming outage reach a user. The checks now mint a
  Firebase custom token as an owner-level operation and exchange it for a real ID token;
  the browser ones reach the page's *own* Firebase instance and sign in through it, so
  everything after that line is the app a signed-in person actually uses. The only thing
  skipped is the Google popup. `check_auth_live.py` runs the other way — it is the one
  check written from outside, where every assertion is something that must *fail*: no
  token, a forged-but-well-formed token, a real challenge id held as if it had leaked.

## What we learned

Tests that never call a model cannot find the bugs that matter. Ours passed while the
system was silently building nothing. Every real defect came from a scripted live run with
full event logging — which is why `scripts/live_walk.py`, `live_climb.py` and
`live_group.py` sit in the repo alongside the unit tests.

The second lesson: when output is wrong, check whether the *data* the model needed even
exists before rewriting the prompt. Attribution failed not because the instruction was
weak but because the journal recorded `"Archivist"` as the actor — the user's name was
never stored anywhere.

The third arrived late and cost the most: **a request that cannot fail cannot teach you
anything.** A session payload shaped one level too deep returned `200 OK` for weeks and
produced three symptoms that looked like three different bugs — a routing bug, a memory
bug, and a permissions bug. One malformed body. What finally exposed it was refusing to
accept an agent's word that it had saved something, and printing the tool calls the UI
actually recorded next to the sentence the agent said.

The fourth: **a control nobody can automate is a control nobody notices has died.** The
feedback button spent months writing rows that no code read, and the thing protecting it
from discovery was a `window.prompt()` that no browser test could get past.

The fifth, and the one we would tell another team first: **check whether the framework
already solved it.** The outage that cost us the most was not a hard problem badly
solved — it was an easy problem solved twice, where our version fought the library's.
Ten minutes reading `starlette/middleware/base.py` would have saved all of it. The same
lesson arrived from the other direction when a security change quietly broke a feature
two files away: scoping the quest list to its owner was correct, and it silently
invalidated the assumption an invite link depended on. **A change is not finished when
the thing you changed works.**

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
- **Anyone with an invite link can join.** Joining is deliberate and authenticated, but
  there is no approval step and no way to remove someone once they are on a party. For a
  link you choose to send that is the intended behaviour; for a link that leaks it is
  not, and we would not ship it to paying teams as-is.
- **Challenges created before sign-in existed are unreachable.** They belong to anonymous
  localStorage ids that now map to nobody. We abandoned them rather than invent an owner
  for data we could not attribute.
- The party roster shows the name and avatar on your Google account. There is no display
  name of your own, and no way to appear as anything else.
- **Memory Bank is personal recall, not the party's memory.** It scopes to
  `(app_name, user_id)`, so it carries what *you* said between *your* challenges. A
  teammate joining a party does not inherit it. The shared layer is `remember_group_fact`
  → Firestore, read wholesale into the prompt, which will not scale past a few dozen
  facts. Calling Memory Bank "shared team memory" would be the easiest overclaim in this
  submission and we are not making it.
