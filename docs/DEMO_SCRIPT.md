# Demo video — shot list and script

**Hard cap: 4:00. Target 3:45.** The rules say "should not be longer than 4 minutes."
Land at 3:45 so an encode hiccup can't disqualify you.

Record this **Aug 26**, not deadline weekend. You ran out of time on the video at your
last two hackathons — that's in your own charter, and it's the single most predictable
failure mode on this project.

---

## Before you hit record

```powershell
cd B:\challenge-accepted
python scripts\seed_demo.py        # instant populated graph, no API cost
python main.py                     # http://localhost:8080/app
```

- **Two browser windows**, side by side, as two different users. There is no sign-in --
  identity is an anonymous id in `localStorage` -- so use **one normal window and one
  incognito window**, or two browser profiles. Do NOT use two tabs — they share
  `localStorage`, so both would be the same user and the party would never reach 2.
  Get the second window's URL from the **Invite** button rather than typing it; that is
  the path a real teammate takes, and it is the one that is tested.
- **min-instances=1** on Cloud Run if demoing the deployed URL. A cold start is several
  seconds of dead air.
- **Pre-run the challenge once** so the tools already exist. Then re-run the FORGE beat
  live for the camera. If a live build fails on camera you have the seeded version to
  cut to — that's why `seed_demo.py` exists.
- Close Slack, email, notifications. Full screen. 1600×900 or larger.
- Have `/api/healthz` open in a tab showing `"store":"firestore"` -- the rules require
  **visual proof of Google Cloud deployment**, and this plus the Cloud Run console is it.

---

## Beats

| Time | On screen | Say |
|---|---|---|
| **0:00–0:20** | Your face, or a blank slide with the tagline | "Last year I asked an AI to help me launch a product. It gave me a beautiful plan. Twelve steps. I did none of them — because every step still needed a tool I didn't have. **Every other AI gives you a plan. This one builds you the tools.**" |
| **0:20–0:50** | Type a real goal into the app | "I tell it what I actually want." Then let the **Interviewer** ask. Pause on a genuinely good question — *"What specific end state would prove to a judge that this launched?"* Say: "It doesn't guess. It asks until the goal is checkable." |
| **0:50–1:20** | Goal Graph draws itself; Journal filling on the right | "Not a to-do list — a dependency graph. Three of these can start today; the rest are blocked. And on the right, the agents are **taking notes** the whole time. That's not a log, it's the product." |
| **1:20–2:20** | **THE MONEY SHOT.** Quartermaster → Toolwright | "Now the part nothing else does. For each step it asks: *what tool would make this trivial?*" Show a ToolSpec appear. Show code being written and **executed**. Show the smoke test pass. **Open the tool and use it.** "It wrote that, ran it, tested it, and attached it to the step. Four of those built in parallel." |
| **2:20–2:50** | Party tab → **Invite** → paste into the incognito window | "Two of us are on this." Click **Invite**, paste the link in the second window. The header goes **1 → 2 in party** on *your* screen, without you touching it. Then have Dana type a discovery — *"the repo has to be public at submission, not just shared with judges"* — and **cut back to your own screen**: it is sitting in your Party Knowledge. "Nobody told me that. I inherited it." |
| **2:50–3:05** | Thumbs down on a tool + reason | "And when something isn't useful, I say so —" click 👎, type a **specific** reason into the inline box ("too generic, I want my own numbers in it") "— and the next generation is built from that sentence. Not a rating. The words." Then ask the agents to rebuild that step and let the new spec's rationale name your objection. |
| **3:05–3:20** | Click **Copy for Claude** on a quest, paste into Claude | "The work doesn't end in my app. One click copies the step, the goal it serves, and the source of the tool it built — straight into whatever I'm already using." Paste it. Let the paste land on screen. |
| **3:20–3:35** | Architecture diagram, then Cloud Console | "Nine agents on Google ADK and Gemini 3.6 Flash, deployed on Cloud Run with Firestore as the shared source of truth." Show the Cloud Run console with the service running. Show `/api/healthz` reading `"store":"firestore"`. |
| **3:35–3:45** | Business model card + live URL | "Nineteen dollars solo, twenty-nine a seat for teams. Measured cost is about 86 cents a challenge." Show the live Cloud Run URL on screen. |

> **Say "Vertex AI Memory Bank" nowhere.** It is not wired — `use_vertex()` is false and
> the architecture diagram marks it *NOT WIRED — PLANNED*. Claiming it on camera is the
> one thing that could turn an honest submission into a dishonest one. "Firestore as the
> shared source of truth" is both true and the better line anyway.

> **Say "challengeaccepted.app" only if you have actually mapped the domain** by
> recording day. Otherwise read out the Cloud Run URL. Do not point judges at a domain
> that 404s.

---

## What must be visibly true on camera

The rubric is Innovation & Operational Utility 40% / Architectural Discipline 30% /
Demo & Production Readiness 30%. Each of these earns a specific slice:

1. **A tool gets written, executed, smoke-tested and used.** Nothing else in the
   category closes this loop. If only one beat lands, make it this one. *(Innovation)*
2. **The graph has real parallel structure.** A chain looks like a to-do list; a DAG
   looks like planning. *(Innovation)*
3. **The Journal is visible.** "Takes notes" is in the track brief verbatim, and most
   entrants will treat it as an implementation detail. *(Track fit)*
4. **Two windows, one challenge, attributed knowledge.** *(Innovation + Demo)*
5. **Feedback changes the next output.** The brief's trailing clause — "constantly
   adapts to the user's unique way of thinking" — is the part most people ignore.
6. **It's deployed, with real auth and real persistence.** Not localhost. *(Demo)*

---

## Do not

- Don't explain the agent roster one by one. Judges see the architecture diagram; the
  video is for showing the thing working.
- Don't apologise for anything or say "in a real product we'd…". Show what works.
- Don't narrate the UI ("now I'm clicking here"). Narrate the *value*.
- Don't run over 4:00. It's a hard cap.

---

## If a live build fails while recording

Say nothing, cut, and use the pre-seeded challenge. The Toolwright degrades to a
checklist by design when a build fails three times — that's honest engineering, but it
is not the beat you want on camera.
