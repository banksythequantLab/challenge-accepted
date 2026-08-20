# Design handoff — Challenge Accepted

Paste the block below into a design session. Everything under it is context for
whoever picks this up.

---

## THE PROMPT — copy from here

> I need a design critique of a hackathon submission that is 11 days from its deadline.
> Two artefacts, in priority order:
>
> **1. A 3-minute demo video** — `_video\challenge-accepted-demo.mp4` (also in Downloads
> as `challenge-accepted-demo-v3.mp4`). 1920×1080, 3:01, narrated. Six of its eleven
> segments are live screen capture of the product; the rest are stills and built cards.
> Two previous videos from this entrant were **rejected for failing to follow directions
> and not showing a demo of use**, so this one is the whole ballgame.
>
> **2. The live product** — https://challengeaccepted.app (Google sign-in required, one
> click). This is what a judge opens after watching the video. The screen that matters
> is the dashboard: a quest map on the left, a chat/journal/party panel on the right.
>
> Critique both for **a judge who has four minutes and forty other submissions to get
> through**. I want ranked, specific findings — what is wrong, where, and the smallest
> change that fixes it. Not a redesign.
>
> Judge against these weights, which are the actual rubric:
> - **40% Innovation & Operational Utility** — does it eliminate real friction? Is the
>   "twist" present? Autonomous execution over chat.
> - **30% Architectural Discipline & Tech Stack** — engineering decisions, decoupling,
>   state management, failure tolerance, security isolation.
> - **30% Demo & Production Readiness** — documentation clarity, unedited live
>   execution, repo quality, setup reproducibility.
>
> Specific questions I want answered:
> - Does the video's **first 30 seconds** land the problem, or does it feel like a
>   product tour? The rules require the problem stated explicitly and early.
> - Is anything **unreadable at 1080p on a laptop**? One segment already had to be
>   rebuilt because it was a screenshot of 12px JSON zoomed until it cropped.
> - Does the pacing hold, or is there a stretch where a tired judge drifts?
> - On the live app: what does a **first-time signed-in user with an empty dashboard**
>   see, and does it tell them what to do? That is the highest-risk screen — the video
>   sells the payoff and this screen has to make good on it within seconds.
> - Is the **quest map** legible as an information graphic, or just pretty? A 15-node
>   DAG with tool badges is the centrepiece.
>
> Out of scope — do not spend effort here:
> - The architecture, the agent topology, the tech choices. They are done and they are
>   the strongest part of the submission.
> - Colour contrast in the abstract. It is already measured both themes: worst case
>   5.60:1 dark, 4.86:1 light, against a 4.5:1 floor. Flag a *specific* element if you
>   find one that fails, otherwise skip it.
> - The Google sign-in wall. It is a deliberate, documented decision (identity is what
>   makes the collaboration and attribution claims possible) and it is not being
>   removed. Critique how the **gate screen** sells it, not whether it should exist.
> - Anything that needs more than a day to implement. Eleven days left, and the video
>   and the submission form still have to be finished.
>
> Give me: findings ranked by score impact, each with the file or screen, the problem
> in one sentence, and the fix. Say plainly if something is already fine — I would
> rather hear "the map works, leave it" than a suggestion invented to fill a list.

## — copy to here

---

## Context the design pass does not need in the prompt, but you might

**What the product is.** You name a goal. Nine agents on Google ADK interview you until
it is checkable by a stranger, decompose it into a dependency DAG of ≤2h tasks, then for
every node ask *"what tool would make this trivial?"* — and write, run and smoke-test
that tool. Live at `challengeaccepted.app`, on Cloud Run.

**What the video shows** — a real run, recorded end to end: a $25k/month rank-and-rent
goal, 15 tasks, 10 tools built, then the agents' own execution trace read back out of
Google Cloud Logging on revision `challenge-accepted-00067-s4f`.

**Already verified, so nobody re-does it:**

| Thing | State |
|---|---|
| Tests | 265 passing |
| Live checks | 34 in `scripts\check_*.py`; 29 green against production |
| Contrast | measured both themes, `scripts\check_a11y.py` |
| Layout | 7 viewports, 320px → 1440px, `scripts\check_devices.py` |
| Tools open and run | `check_tool_render.py --browser`, 0 console errors |
| Video length | 3:01, cap is 4:00 |

**Deadline:** 31 Aug 2026, 5:00pm PDT. Judging 1 Sept – 1 Oct.

**Still outstanding, and none of it is design work:**
1. Upload the video to YouTube **public** (not unlisted — unlisted scores zero).
2. Paste into the Devpost form: hosted URL, repo, architecture image, the text
   description from `docs/DEVPOST.md`, and the three bonus links below.
3. Select the **Collaborative Partner** category.

**Bonus links already earned (+0.6), just need pasting into the form:**
- Published content: https://gist.github.com/banksythequantLab/d1b85fd03719542f72341bd69d9077aa
- Social post: https://x.com/banksythequant/status/2090201173580001327
- Additional model (Gemma 4): evidenced at https://challengeaccepted.app/api/healthz

**Files worth opening:**
- `docs/SUBMISSION_CHECKLIST.md` — every requirement quoted verbatim from the rules
- `docs/DEVPOST.md` — the text description, already accuracy-passed
- `docs/architecture.png` — the diagram the submission attaches
- `_video/script.md` — the narration, segment by segment, with requirement tags
- `README.md` — the "Verified live" table, every row re-checked against revision 00067

## Hackathon links

- **Rules and full scoring rubric** — https://allthingsagentichackathon.devpost.com/rules
- **Main page** — https://allthingsagentichackathon.devpost.com/
- **Resources** — https://allthingsagentichackathon.devpost.com/resources
- **Your submissions** — https://devpost.com/my/submissions
