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

**v0.4 -- deployed, and driven end to end from the browser.**

**Live:** https://challenge-accepted-xk3m7ygefa-uc.a.run.app/app
(dashboard) · [`/`](https://challenge-accepted-xk3m7ygefa-uc.a.run.app/) (ADK dev UI) ·
[`/api/healthz`](https://challenge-accepted-xk3m7ygefa-uc.a.run.app/api/healthz)

| | |
|---|---|
| Verified live | 8-turn interview -> charter saved -> 12-node DAG -> 6 tools built, smoke-tested and persisted |
| Verified live | Warden -> `forge` transfer via `transfer_to_agent`; Quartermaster `output_schema`; parallel Toolwrights executing real code |
| Verified | 110 tests pass against a real ADK `Runner`, plus 13 browser-driven checks that click the actual controls; FastAPI boots, `/api/healthz` 200 |
| Measured | One full challenge (12 nodes, 6 tools) = **243k prompt / 66k billed output, ~$0.86**. Break-even at $29/seat ≈ **34 challenges/user/month** |
| Fixed | The "exactly 4 tools" ceiling. Two causes, both live-only. See Known issues. |
| Verified live | CLIMB end to end: node closed on evidence, feedback captured with reason, blocker -> group fact -> interview re-opened -> graph redrawn around the constraint |
| Verified live | **Two users, one challenge.** Dana joins a session Derek started; her Coach opens with *"Derek found Cloud Run requires billing... so we're using Render and Vercel instead"* and hands her a ready node. This is the demo beat |
| Verified | **A joining teammate is handed live work, not finished work.** This row said *Not verified* for weeks. `scripts\check_handoff.py` now drives it: Dana joins cold on a challenge with two closed nodes and asks what to pick up. She gets both party facts (one attributed to Derek by name) and is pointed at an open node; neither finished node is named |
| Verified live | **Deployed to Cloud Run**, Firestore-backed (`store=firestore`), agents served from Vertex AI. Gemini 3.x lives on the Vertex **global** endpoint, not a regional one |
| Verified live | The dashboard **drives** the agents: chat panel opens an ADK session, streams `/run_sse`, and renders text, tool calls and code execution as they happen. One scripted browser run: 15 quest nodes drawn, 4 tools forged, title auto-filled, zero console errors |
| Verified | Losing the session mid-conversation (deleted server-side, exactly as a Cloud Run restart does) recovers without a reload -- `scripts\check_session_recovery.py` |
| Verified | Every copy-to-clipboard path returns the right markdown, on desktop and on an iPhone 13 viewport -- `scripts\check_copy.py` reads the clipboard back and asserts on content |
| Built | Conversations persist in Firestore via a custom `BaseSessionService`, registered under a `firestore://` scheme through ADK's own service registry. Survives an instance swap and a redeploy |
| Not built | Vertex AI Memory Bank. `use_vertex()` is false. See Known issues |
| Not built | Firebase Auth. Users are anonymous ids in `localStorage` |

Reproduce with `python scripts\live_walk.py` (costs ~$0.86, prints full token accounting).

**Token accounting gotcha:** thinking tokens bill as *output* on Gemini 3.x and are
reported in `thoughts_token_count`, separate from `candidates_token_count`. Summing
candidates alone under-reported cost by up to 3x -- measured 725 thinking vs 251 visible
on one short call. `live_walk.py` now sums both; anything estimating cost must too.

Run `pytest` to see exactly what is and isn't covered.

---

## Run it locally

Python 3.11+. No build step -- the dashboard is a single static file.

```powershell
git clone https://github.com/banksythequantLab/challenge-accepted
cd challenge-accepted

python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

pytest                                 # 110 tests, no API key needed
```

To talk to the agents you need one key. Get a free one at
[aistudio.google.com](https://aistudio.google.com/apikey):

```powershell
copy .env.example .env                 # macOS/Linux: cp .env.example .env
# edit .env and set GOOGLE_API_KEY=...

python main.py
```

Then open:

| | |
|---|---|
| http://localhost:8080/app | the dashboard -- talk to the agents, watch the quest map |
| http://localhost:8080/ | ADK's dev UI, useful for inspecting raw agent events |
| http://localhost:8080/api/healthz | `{"ok":true,"store":"memory",...}` |

With no `GOOGLE_CLOUD_PROJECT` set the store falls back to an in-process dict, so
everything runs with zero GCP setup. Nothing persists between restarts in that mode --
that is expected, and `store` reports `memory` so you can tell.

### Verify it end to end

These drive the real thing rather than mocking it. The first three cost a few cents of
Gemini usage; the rest are free.

```powershell
python scripts\drive_chat.py            # types 4 interview turns into the real chat box
                                        # in a headless browser; fails unless the agents
                                        # reply AND a challenge_id reaches the UI
python scripts\check_party.py           # TWO browser contexts: one user invites, the
                                        # other joins and discovers something, and the
                                        # first screen must pick it up on its own poll
python scripts\check_session_recovery.py  # deletes the session mid-conversation and
                                        # proves the page recovers without a reload
python scripts\check_tools.py           # opens all five tool types and asserts the
                                        # right renderer fired; runs the mini-app
python scripts\check_climb.py           # clicks Work on this, reports a step done with
                                        # evidence, and requires the map to turn it
                                        # green without a reload
python scripts\check_feedback.py        # clicks thumbs-down and follows the objection
                                        # all the way into the Quartermaster's prompt
python scripts\check_forge_ui.py        # replays a synthetic ADK stream; asserts the
                                        # worker lanes fill and the read side does NOT
                                        # freeze while the agents work
python scripts\check_phone.py           # the whole app on an iPhone 13 with real taps
python scripts\check_handoff.py         # a teammate joins cold and asks what to do;
                                        # fails if the Coach leads with a node that
                                        # was already finished before she arrived
python scripts\check_a11y.py            # tabs the quest map, opens a tool with Enter,
                                        # and computes contrast from rendered colours
python scripts\check_errors.py          # 429, 500, a stream that dies halfway, and one
                                        # that recovers -- asserts each says what
                                        # happened, whether work survived, and offers
                                        # Try again with the message still in hand
python scripts\check_poll_cost.py       # counts Firestore round trips for ONE idle
                                        # browser with 25 challenges in the store, and
                                        # fails if the read path goes quadratic again
python scripts\check_copy.py            # clicks every copy button and reads the
                                        # clipboard back, desktop and iPhone viewport
python scripts\shoot_ui.py              # seeds demo data, screenshots the dashboard
```

`check_party.py` is the one that earns its keep. Three separate bugs — a silently
reshaped session payload, a group id resolved from the wrong place, and an agent
claiming a write it had no tool to perform — were all invisible to the unit tests and
to a single browser. Two browsers found them in one run.

`drive_chat.py` also takes a URL, so it can drive a deployment:

```powershell
python scripts\drive_chat.py https://challenge-accepted-xk3m7ygefa-uc.a.run.app
```

---

## Deploy it

Needs the [gcloud CLI](https://cloud.google.com/sdk/docs/install) and a GCP project
with billing enabled.

```powershell
gcloud auth login --no-launch-browser
gcloud config set project YOUR_PROJECT_ID

.\deploy\deploy.ps1 -ProjectId YOUR_PROJECT_ID -KeepWarm
```

The script enables the required APIs, creates the Firestore database if missing, builds
with Cloud Build, and deploys to Cloud Run with `GOOGLE_CLOUD_LOCATION=global`.
`-KeepWarm` sets `min-instances=1` so a cold start does not eat a live demo.

**It does not grant IAM.** Since Google's 2024 change to the default compute service
account, a fresh project needs these before the first build will succeed. Run them once:

```powershell
$PROJECT = "YOUR_PROJECT_ID"
$NUM = gcloud projects describe $PROJECT --format="value(projectNumber)"
$SA = "$NUM-compute@developer.gserviceaccount.com"

foreach ($role in @("roles/cloudbuild.builds.builder","roles/storage.objectViewer",
                    "roles/logging.logWriter","roles/artifactregistry.writer",
                    "roles/datastore.user","roles/aiplatform.user")) {
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role=$role
}
```

Without `datastore.user` the app starts but falls back to the in-memory store; without
`aiplatform.user` the agents 403 on the first turn.

Then confirm the store actually switched -- a silent fallback to `memory` means no
persistence and each instance holding its own private dict:

```powershell
curl https://YOUR-SERVICE-URL/api/healthz     # expect  "store":"firestore"
.\deploy\smoke_live.ps1                       # creates a session and takes one real turn
```

Two things that will bite you, both learned the hard way:

- **Gemini 3.x is served from the Vertex `global` endpoint**, not a regional one. A
  regional `-ModelLocation` gives `404 NOT_FOUND: Publisher model`. The script defaults
  to `global`.
- **PowerShell does not throw on a non-zero exit from a native executable.** An earlier
  version of the deploy script cheerfully printed `==> Deployed` over a failed build.
  It now checks `$LASTEXITCODE` after every `gcloud` call.

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
|   +-- referee     AgentTool          CLIMB   evidence check + feedback capture
+-- archivist       mode=single_turn   --      takes the notes (cross-cutting)
+-- scout           AgentTool                  grounded search, on demand

browser  ->  /run_sse  (SSE stream of every agent event)
         ->  /api/*    (read-only: graph, journal, tools, group facts, feedback)
         ->  Firestore (the shared data source both sides hit)
```

The Referee hangs off the Coach as an `AgentTool`, not as a sibling. As a sibling it
caused an infinite delegation loop in a live run -- see Known issues.

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

### Fixed: conversations lived on the instance that started them

I had been writing, in this file, that "sessions live in the server's memory". That was
wrong in the detail and right in the consequence, which is the worst way to be wrong.
With `session_service_uri=None` ADK does **not** use an in-memory service — it falls
back to **per-agent SQLite** under `<agents_dir>/<agent>/.adk/`. Same outcome on Cloud
Run: that file is per-instance and ephemeral.

Two failure modes follow, and both land squarely in a seven-week judging window:

* `max-instances=10` with no session affinity means a judge's *second message* can be
  routed to an instance that has never heard of their session. The dashboard notices
  and rebuilds it, so nothing errors — the conversation history simply vanishes and the
  Interviewer starts over. **Silent amnesia is worse than a visible failure.**
* Any redeploy or instance recycle loses every in-flight conversation.

`challenge_accepted/services/session_store.py` is a `BaseSessionService` backed by the
same Firestore as everything else, registered under a `firestore://` scheme through
ADK's own service registry — the documented extension point, not a monkey-patch.
Events live in their own collection rather than an array on the session document:
Firestore caps a document at 1 MiB and appending to an array rewrites the whole
document each time, which is O(n²) bytes written over a conversation.

`--session-affinity` is now set too, but it is an *optimisation*, not the fix. Cloud Run
drops affinity the moment an instance goes away — which is exactly when durability has
to carry it.

**The trap this hid.** The first version put the Firestore writes on
`asyncio.to_thread`, for the obvious reason that a blocking client should not sit on the
event loop. It passed 91 unit tests and every browser check except the one driving a
real FORGE turn, which died mid-stream: `ERR_INCOMPLETE_CHUNKED_ENCODING` in the
browser, an ASGI exception group terminating in `GeneratorExit`, and a wall of
OpenTelemetry "Failed to detach context". ADK runs agents as nested async generators
wrapped in `Aclosing`, and `append_event` is called from inside them — a thread hop is a
real suspension point, so the loop interleaved teardown with the write and closed the
generator underneath it. The user's agents stopped halfway through building their tools.

The writes are synchronous now, deliberately, with a test that drives the coroutine by
hand and fails if it ever yields. Reads keep their thread hop: they are called from
ordinary request handlers, not from inside a generator.

### Memory Bank: wired at both ends, still switched off

Until now `main.py` set `memory_service_uri` and that was the entire integration.
Nothing read memory and nothing wrote it, so setting `AGENT_ENGINE_ID` would have
produced a configured service that no code path ever consulted — the same shape as the
feedback button that recorded verdicts no reader ever queried. "The wiring exists" was
true of the URI and false of the feature.

Both ends now exist:

* **Read** — ADK's `preload_memory` on Warden and the Interviewer. It is not
  model-callable: it hooks `process_llm_request`, searches with the user's own words and
  appends hits as dynamic instructions, so it costs nothing against the tool-count
  ceiling. It is wired unconditionally, including under test, because ADK's
  implementation swallows every exception out of `search_memory` — wiring it only in
  production would mean the agent we test is not the agent we ship.
* **Write** — `save_charter` and `complete_node` hand the session to the memory service.
  Those are the two moments a durable fact exists; ingesting every turn would re-send
  the whole session for consolidation after turns that decided nothing. Both calls are
  best effort. A charter that fails because a nice-to-have recall layer had a bad minute
  is a worse product than one that quietly remembers less.

**It is personal recall, not the party's memory, and the code says so.** Memory Bank
scopes to `(app_name, user_id)`. The shared notebook is `remember_group_fact` →
Firestore `groups/{id}.shared_facts`. The two look alike in a diagram and are not the
same thing; conflating them would promise a teammate a memory they do not share.

**One env var used to move two subsystems.** `use_vertex()` gated sessions *and* memory,
so switching on Memory Bank would also have moved every conversation off the Firestore
session service — the code with the test asserting `append_event` never yields to the
event loop. Nothing would have failed; sessions would just have been served by code with
no coverage here. That is now `use_memory_bank()` and `use_vertex_sessions()`, sessions
stay put unless `CA_SESSIONS=agentengine`, and `/api/healthz` reports `memory` and
`sessions` separately so a deploy states which backends it is on.

Still switched off in production: no Agent Engine exists yet, so `use_memory_bank()` is
false and `/api/healthz` reports `"memory":"none"`. Creating one needs a `gcloud auth
login` that has expired. **No claim is made here that Memory Bank has stored or recalled
anything** — that is unproven until a live run does it, and there is no check in
`scripts/` for it yet.

The architecture diagram used to draw Memory Bank, Agent Sessions and a persistent
Agent Engine code sandbox as though all three were running. They were not. Those cards
are now dashed and labelled **NOT WIRED — PLANNED**, with a legend explaining the
convention, and the code-execution card names the `BuiltInCodeExecutor` actually in use.
The top band claimed a Next.js client with Firebase Auth and React Flow; the real client
is one static HTML file with anonymous ids in `localStorage`, and it says that now.

A diagram that describes what you wish you had built is worth less than no diagram.

**The client-side belt to that braces.** Even with durable sessions, a client can hold
an id the server will not honour — a wiped collection, a session deleted out from
under it. The dashboard detects a session the server has never heard of, rebuilds it,
and retries the turn once — no reload, no lost conversation.
`scripts\check_session_recovery.py` proves it by
deleting the session out from under a live page and requiring the next turn to succeed.

### Fixed: the quest map was mouse-only, and the labels failed contrast

`scripts\check_a11y.py` drives three things a judge could actually hit, and all three
were broken:

* **All 11 quest nodes were unreachable by keyboard and had no accessible name.** They
  are SVG `<g>` elements with click handlers, which are invisible to Tab and announced
  as nothing. The map is this product's centrepiece, so a mouse-only map is a mouse-only
  product. They now carry `tabindex`, `role="button"` and a label that reads the way
  someone would say it aloud — *"Pick hosting that isn't Cloud Run. blocked, 1 tool,
  about 60 minutes"* — plus Enter/Space handling, because a `role` the element does not
  honour is worse than no role. Selecting a node redraws the SVG, so focus is explicitly
  restored to its replacement; otherwise the keyboard user is dumped back at the top of
  the page on every click.
* **The tool viewer did not move focus.** A keyboard user opening it was still tabbing
  through the map behind a full-screen overlay. It now takes focus, is marked
  `role="dialog" aria-modal="true"`, and returns focus to the button that opened it.
  (Escape already worked.)
* **`--faint` measured 3.18:1** — below WCAG AA's 4.5:1 for body text, and it carries
  the stat labels, the map legend and the party roster. Unreadable on a projector,
  which is exactly where a hackathon demo gets seen. Now `#828A9E`, measured at
  4.98–5.63:1 across all three panel backgrounds.

Contrast is computed **from the rendered colours**, walking up ancestors for the first
non-transparent background, rather than read off the stylesheet — so it reflects
whatever actually won the cascade.

### Fixed: a failed run showed you a status code and nothing else

Over seven weeks of judging a run *will* fail — Gemini rate-limits, an instance
recycles mid-stream, hotel wifi drops. What you got was a dashed chip reading
`✖ run_sse 429`: a status code, no idea whether your work survived, and no way forward
but retyping the message you had just watched scroll into the transcript.

Now each failure says what happened, **whether any of it stuck**, and offers Try again
with the original message still in hand. That middle part is the one that matters: the
client tracks whether any agent event arrived before the break, so a mid-stream death
says *"the agents had started — whatever they saved is on the map"* while a pre-stream
429 says *"nothing was saved, so nothing is half-done."* The agent messages that did
arrive stay on screen rather than being wiped.

The connection indicator also had a real problem: a dot changing from green to red was
the **entire** signal, which is nothing at all to a colour-blind user, and it meant a
stale map looked exactly like a quiet one. The label under it now reads `live` /
`offline`.

`scripts\check_errors.py` drives four scenarios against a fake server that returns
exactly the failure it is named after — 429, 500, a stream that dies halfway, and one
that recovers on retry.

**Two things that check found immediately.** First, `$('send').onclick = send` — an
onclick handler is called with the MouseEvent, which arrived as the new retry-text
argument and threw on `.trim()`, eating the whole turn *including the error handler
meant to report it*. Second, the first version of the "recovers" scenario failed only
the first attempt and never showed an error at all: `startRun` already retries once by
itself, so a single transient failure never reaches the user. Good behaviour, and worth
knowing — to test the user's Try again you have to get past the client's own retry.

The script now captures `pageerror` and console errors. Without that, its first run
just timed out waiting for an error chip with no hint that JavaScript had thrown.

### Fixed: an idle browser cost 570 Firestore reads a minute

Making the map update live (below) turned the read path from an occasional cost into a
standing one — every 4s idle, every 1.2s during a run, per open browser, for a
seven-week judging window. So I measured it rather than assuming it was fine.
`scripts\check_poll_cost.py` counts real Store round trips with 25 challenges in the
store and one browser sitting still:

```
before   570 reads/min   (81 node queries in 12s)
after     75 reads/min   (3)
```

Two causes:

* **`/api/challenges` ran one node query per challenge** to compute a count the picker
  never rendered. That grew linearly with every quest any previous visitor had created,
  and it ran on every poll. Counts are now opt-in (`?counts=1`), the list is capped, and
  the browser fetches it **once** — plus when a turn creates a quest, which is a thing
  it gets told about rather than something worth asking 50 times a minute.
* **The poll was four requests** — summary, graph, journal, tools — so four separate
  existence checks and a second pass over nodes and tools. There is now one
  `/dashboard` endpoint doing each read exactly once: five reads instead of twelve, and
  one round trip instead of four on every frame of the animation this thing is judged
  on. The four endpoints remain, and a test asserts `/dashboard` returns byte-identical
  payloads — if they drift, the browser and the checks are testing different products.

`get_journal` was also calling `list_journal` twice: once for the window, once to count
the thing it had just fetched.

### Fixed: the whole read side froze while the agents worked

```js
setInterval(() => { if (!busy) refresh(); }, 4000);   // the old line
```

`busy` is true for the entire length of a run, and a FORGE run is about a minute. So
during the one stretch where the map grows from nothing to eleven nodes, four tools get
built in parallel and the journal fills with agent decisions, **the screen showed none
of it** and then snapped to the finished state at the end. The most interesting thing
this system does was invisible while it was happening.

It now polls *faster* while a run is live (1.2s) than when idle (4s), and skips only the
one thing that would be destructive — rebuilding the quest panel while you are typing
into it.

Alongside that, two things that made parallelism unreadable:

* Action chips carried no author, so four Toolwrights building concurrently rendered as
  an anonymous column of "writing code…" — one agent stuttering, not four working.
  Every chip is now attributed.
* A new **forge rail** draws a lane per worker, each showing writing code → smoke test
  passed → shipped ✓, with failures marked red until the retry succeeds. Parallelism is
  a shape now instead of a claim.
* An empty Toolwright slot is told to say "idle" and stop, which is correct for the
  agent and wrong for the screen: the loop runs several passes over four slots, so a
  real turn buried the work under bubbles that said nothing. Those are suppressed; the
  rail carries that information instead.

`scripts\check_forge_ui.py` replays a synthetic ADK event stream — deterministic, free,
and able to assert on *timing*, which a live run cannot. It fails if fewer than two
lanes are live mid-stream, or if the read side did not refresh at all during the run.

### Fixed: three ways the app was broken on a phone

`scripts\check_phone.py` drives an iPhone 13 viewport with real taps. It found:

* **The composer was 13px and the feedback field 12px.** iOS Safari force-zooms the
  page when you focus an input under 16px *and does not zoom back out* — so the first
  tap into either one stranded the user at 1.3× with the layout off the right edge.
  Both are 16px on small screens now. This is a threshold, not a preference.
* **Invite was a 30px tap target.** Buttons get `min-height:36px` on touch.
* **The Copy chip covered the words it was offering to copy.** It is permanently
  visible on touch (correct — reveal-on-hover means never on a phone), so bot bubbles
  now reserve room for it rather than letting it float over the first line.

### Fixed: the feedback button was decorative

The pitch says *"when something isn't useful I say so, and the next generation is
different."* It was not. `record_feedback` wrote a Firestore row and **nothing in the
codebase ever read it** — `read_challenge_state` did not return it, no prompt mentioned
it, and a grep for readers came back empty. The next generation was identical.

There was a second reason it had gone unnoticed for so long: the reason box was a
native `window.prompt()`. That blocks the page, so no browser check could ever click
the button. An untestable control is a control that rots.

Three changes:

* `read_challenge_state` now returns `tool_feedback`, **resolved** — a raw row carries
  a `tool_...` id, which no model can reason about, so each entry names the node, the
  tool and its type, with thumbs-down first.
* The Quartermaster carries an `output_schema`, and an ADK agent with an output schema
  gets **no tools** — so it could not have looked the feedback up even if it wanted to.
  Its instruction is now an `InstructionProvider` that injects the rejections, with the
  user's own words, plus a table mapping common objections to what must change.
* The reason box is inline, styled, and non-blocking.

`scripts\check_feedback.py` clicks the button in a real browser, fails loudly if a
native dialog appears, and then follows the objection all the way to the Quartermaster's
actual prompt string. It asserts the prompt *differs* with and without the feedback —
because "the loop is closed" and "the loop is open" otherwise look identical.

### Fixed: the browser posted session state to an endpoint that silently reshaped it

This one hid three separate "mysteries" behind a request that returned `200 OK`.

The dashboard created its ADK session with

```js
POST /apps/{app}/users/{u}/sessions/{sessionId}   { "state": { user_id, group_id, challenge_id } }
```

That endpoint is deprecated in ADK, and it declares `state: Optional[dict[str, Any]]` as
a **bare body parameter** — the whole body *is* the state. So the session was created
with state literally equal to `{"state": {...}}`, one level too deep. FastAPI validated
it. Nothing logged. Every later read of `tool_context.state["challenge_id"]` and
`["user_id"]` simply missed.

Downstream, that produced:

* **Every challenge created from the dashboard was owned by `anon` in group `grp_anon`.**
  `save_charter` falls back to `state.get("user_id", "anon")`. Group memory was
  effectively one global bucket.
* **A teammate opening an invite link resolved to their own private group.** Their
  discoveries were filed where nobody would read them.
* **Warden re-interviewed people about a goal already drawn on screen**, because the
  in-flight check reads `challenge_id` from state and never found one.

Fixed by posting to the supported plural endpoint, which takes a typed
`CreateSessionRequest{session_id, state, events}` — so the wrapping is explicit and a
mismatch is a validation error instead of a shrug.

The lesson is not "read the docs." It is that a request which cannot fail is a request
that cannot tell you anything, and the only thing that caught this was driving two real
browsers and refusing to accept an agent's word that it had saved something.

### Fixed: a teammate could see the party, but never join it

Group facts *read* correctly for anyone opening `?id=<challenge>` — `/api/challenges/{id}`
resolves the group from the challenge document. Writes did not: `_group_id()` trusted
session state, which carries a `grp_<user_id>` the browser minted from its own
`localStorage`. `_group_id()` now resolves through the challenge whenever one is in
scope, and only falls back to state before a charter exists.

Party membership is now a deterministic `POST /api/challenges/{id}/join` the browser
makes on load, **not** something inferred from a model deciding to call a tool. The
first version relied on the latter, so a teammate could read a quest for five minutes
while both screens still said "1 in party". The header shows the roster, and the Party
tab has an **Invite** button that copies the exact link.

`scripts\check_party.py` drives the whole beat through two separate browser *contexts*
(not tabs — tabs share `localStorage` and would let a broken build pass): Derek opens
the quest, copies the invite, Dana joins in a fresh context, tells the agents something
new, and Derek's screen picks it up on its own poll.

### Fixed: Warden claimed to save a group fact it had no tool to save

With routing fixed, Warden answered a teammate with *"I've recorded that into our shared
group memory so everyone inherits it."* Nothing was written — `remember_group_fact` was
on Archivist and Coach, not on Warden. It was a sentence the model made up because the
sentence was the obviously right thing to say.

Warden now holds the tool. An agent that can *claim* a thing must be able to *do* the
thing; the alternative is a product whose central promise is a hallucination. The check
script now prints the tool calls the UI recorded next to what the agent said, which is
what separates "the tool never fired" from "the tool fired and the write was dropped".

### Fixed: a redirected deploy died on line 2 and looked like it was still running

`deploy\deploy.ps1` set `$ErrorActionPreference = "Stop"`. gcloud writes advisories to
stderr (`[environment: untagged] Read more to tag: ...`), and under `Stop` PowerShell
promotes native stderr to a **terminating** error as soon as the script's streams are
redirected. Run interactively it worked; run as `.\deploy\deploy.ps1 ... *> deploy.log`
it died on an informational notice and left a two-line log that read exactly like a
deploy that was merely slow.

Now `Continue`, with correctness resting on explicit `$LASTEXITCODE` checks. The
Firestore existence probe was rewritten the same way — it used `try/catch`, which only
catches when stderr happens to be converted, so on a fresh project it could report the
database as existing and skip creating it.

### Fixed: a joining teammate got interviewed instead of onboarded

Dana opened a challenge Derek had already planned. Warden delegated her to the
**Interviewer**, which asked "what are Dana's primary technical skills?" -- re-running
ACCEPT on someone whose entire reason for being there is to *inherit* an existing plan.
Warden's rule "never skip ACCEPT" was written for a new challenge and silently applied
to a new person. Added an explicit rule: if `read_challenge_state` returns a charter
AND nodes, go straight to `coach`, whoever is talking.

**Then attribution failed for a data reason, not a prompt reason.** With routing fixed,
the Coach said *"the team found Cloud Run needs billing..."*. Tightening the prompt
could not have fixed it: `remember_group_fact` journalled the actor as `"Archivist"`,
so Derek's name was never recorded anywhere. The journal now records the acting **user**
as the actor, and `read_challenge_state` returns `recent_journal` so the Coach can match
a fact to the person who hit it. Result: *"Derek found Cloud Run requires billing
enabled and nobody on the team has admin access, so we're using Render and Vercel."*

Worth remembering: the first instinct was to reword the prompt. The prompt was fine.
The data it needed did not exist.

**And the rule did not hold.** Proven by script, that fix looked complete. Driven
through two real browsers it failed immediately — partly because of the session-state
bug above, but also because a rule sitting eighth in a list of eight competes with the
other seven and loses. Warden's instruction is now an ADK `InstructionProvider`: when
state carries a planned challenge, the prompt is rebuilt each turn with the actual
title, outcome and progress, stated as fact rather than policy. Rules argue. Facts
don't. See `warden_instruction()` in `challenge_accepted/agent.py`.

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
  api.py              /api/* read API for the dashboard
  static/app.html     the dashboard: chat, quest map, journal, party. One file, no build
  services/
    store.py          Firestore repository, in-memory fallback
    tools.py          ADK FunctionTools over the store
main.py               Cloud Run entrypoint via get_fast_api_app
tests/                110 tests, no API key required
scripts/              live walkthroughs and browser-driven end-to-end checks
deploy/               deploy.ps1, check.ps1, smoke_live.ps1, SETUP.md
docs/                 plan + architecture diagram
```

## Next

1. **Vertex AI Memory Bank.** Read and write are both wired now -- `preload_memory` on
   Warden and the Interviewer, `add_session_to_memory` from `save_charter` and
   `complete_node` -- and 13 tests pin the behaviour, including that a dead memory
   service cannot stop a charter saving. What is missing is the Agent Engine itself:
   `use_memory_bank()` is false in production and `/api/healthz` says
   `"memory":"none"`. Creating one needs `gcloud auth login` (the token on this machine
   has expired), then `AGENT_ENGINE_ID` on the service and a redeploy.

   **Nothing here claims Memory Bank has stored or recalled anything.** Until a live
   run does it, the only honest statement is that the code paths exist and are tested
   against fakes. The check that would settle it does not exist yet: run one challenge
   to a saved charter, start a second challenge as the same user, and assert the
   Interviewer skips a question it already has the answer to.

   Note it is *personal* recall -- Memory Bank scopes to `(app_name, user_id)`. The
   party's shared memory is `remember_group_fact` -> Firestore, and that has worked all
   along.
2. Firebase Auth, replacing the anonymous `localStorage` ids.
3. **Map `challengeaccepted.app`.** Blocked on domain verification, not on code. The
   mapping resource now exists in `us-central1` and reports exactly what it is waiting
   for:

   ```
   Ready=False  reason=PermissionDenied
   Caller is not authorized to administer the domain challengeaccepted.app.
   ```

   DNS for the domain is on Cloudflare (`dalary`/`kolton.ns.cloudflare.com`) and the zone
   is empty -- no A, AAAA, CNAME or TXT at the apex. `gcloud domains list-user-verified`
   returns 15 domains and this is not one of them, so Cloud Run will not make the domain
   routable and will not provision a certificate.

   Three steps remain, and only the first needs a human:

   1. In Google Search Console, add a **Domain** property for `challengeaccepted.app`,
      copy the `google-site-verification=...` TXT value, add it at the Cloudflare apex,
      then Verify. Verifying the apex covers `www` and every other subdomain.
   2. Re-read the mapping; `status.resourceRecords` then carries the A/AAAA records to
      add. Read them from the API rather than hard-coding them from memory.
   3. Add those records in Cloudflare as **DNS only** (grey cloud). Google's managed
      certificate cannot be issued through Cloudflare's proxy, and leaving the proxy off
      also keeps the agent event stream unbuffered.

   The obvious Cloudflare-side shortcut -- a proxied CNAME plus an Origin Rule rewriting
   the `Host` header to the `run.app` hostname -- does not apply: Host header override,
   SNI override and DNS record override are all Enterprise-only. A Worker would work on a
   free plan, but it puts a proxy in front of an SSE stream for no gain over DNS-only.

   Until this lands, the Cloud Run URL is the only address worth putting on camera -- and
   `docs\DEMO_SCRIPT.md` says so.

---

## How this was built, and what that taught

**Tests that never call a model cannot find the bugs that matter.** All 110 pass, and
they passed the entire time the system was silently building nothing. The 4-tool
ceiling, the delegation loop, the dropped feedback, the duplicated group facts, the
read-only dashboard -- every one surfaced in a scripted live run with full event
logging, and none was reachable from a test suite that mocks the model.

So the checks in `scripts/` are the ones worth reading. They boot the real app, drive
the real browser, and assert on real output: the clipboard is read back rather than
trusting a button that says "Copied", and the session-recovery check deletes the session
out from under the page rather than trusting that recovery code runs.

**When output is wrong, check whether the data the model needs even exists before
rewriting the prompt.** The teammate-attribution bug read exactly like a prompt problem.
The prompt was fine; the journal was recording `"Archivist"` as the actor, so the user's
name had never been stored at all.
