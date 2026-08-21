# Submit — the runbook

Everything below is paste-ready. Work top to bottom; nothing here needs a decision.

**Deadline: 31 Aug 2026, 5:00pm PDT.** Submit with a day of slack, not an hour.

Verified today, 20 Aug:

| Thing | State |
|---|---|
| `challengeaccepted.app/api/healthz` | `ok:true`, `store:firestore`, `vertex:true`, `auth:required`, archivist = `gemma-4-26b-a4b-it-maas` |
| Repo `main` | `99436c6`, in sync with `origin/main` |
| Video | `_video\challenge-accepted-demo.mp4` — **3:01.1**, 18 MB, 1920×1080, captions burned in |

---

## 1 · YouTube

Upload `challenge-accepted-demo.mp4`.

**Visibility must be `Public`. Not `Unlisted`.** The rules say "made publicly visible";
an unlisted link is a submission that scores nothing. Set it, then open the watch URL in
a private window to prove it.

Other settings: **No, it's not made for kids** · no age restriction · category
*Science & Technology* · captions are burned into the picture, so nothing to upload.

### Title

```
Challenge Accepted — nine agents that build the tools your goal actually needs
```

### Description

```
Every AI I asked for help with a goal gave me a plan. A good one. I did none of it,
because every step still needed something I didn't have — a spreadsheet model, a
comparison of four vendors, a script I'd never written.

The plan was never the missing piece. The tools were.

Challenge Accepted takes one sentence about something you want to be true, interviews
you until the goal is checkable by a stranger, breaks it into a dependency graph of
two-hour tasks, and then — for every node — asks what tool would make that step
trivial, writes it, runs it, and smoke-tests it.

This video is one real run on the deployed site: my own goal, $25,000/month in 90 days
from directory and rank-and-rent sites, starting from $0, a $1,500 budget and 34
domains. 15 tasks. 10 working tools.

Try it: https://challengeaccepted.app
Code:   https://github.com/banksythequantLab/challenge-accepted

Built with Google ADK · Gemini 3.6 Flash · Gemma 4 · Cloud Run · Firestore ·
Vertex AI Memory Bank.

Created for the All Things Agentic Hackathon (Collaborative Partner track).

00:00 The plan was never the missing piece
00:21 What it does
00:43 A real run — $25,000/month in 90 days
01:02 Five questions, until a stranger could check it
01:16 15 tasks as a dependency graph
01:25 It starts with unit economics
01:37 Eight tool builders at once
01:51 Built for my 34 domains and my $1,500
02:12 Running on Google Cloud
02:35 A teammate's coach opens with your findings
02:47 9 agents · 15 tasks · 10 working tools
```

Tags: `agents, google adk, gemini, gemma, cloud run, firestore, vertex ai, hackathon,
multi-agent, goal setting`

---

## 2 · Devpost form, field by field

<https://allthingsagentichackathon.devpost.com/> → Enter a submission.

| Field | What goes in |
|---|---|
| **Project name** | `Challenge Accepted` |
| **Elevator pitch** | `Name a goal. Nine agents interview you, break it into a dependency graph, then write and test the tool every step actually needs.` |
| **Description** | Paste `docs/DEVPOST.md` — the whole thing, minus the top four lines of front-matter |
| **Built with** | `python`, `google-adk`, `gemini`, `gemma`, `google-cloud-run`, `firestore`, `vertex-ai`, `firebase-auth`, `javascript` |
| **Try it out** | `https://challengeaccepted.app` |
| **Video demo** | the YouTube watch URL from step 1 |
| **Repository** | `https://github.com/banksythequantLab/challenge-accepted` |
| **Architecture diagram** | upload `docs/architecture.png` as an **image**. Not a link |
| **Category** | **Collaborative Partner** — one only |

### The three bonus URLs

These are already earned and published. They are worth **+0.6 on a 1–6 scale** and
every one of them scores zero until its URL is in the form.

```
Published content   https://gist.github.com/banksythequantLab/d1b85fd03719542f72341bd69d9077aa
Social post         https://x.com/banksythequant/status/2090201173580001327
Additional model    https://challengeaccepted.app/api/healthz     (Gemma 4 named per tier)
```

### Paste this into the description too

It gets ahead of the one thing a judge might otherwise bounce on:

> **Signing in.** Challenge Accepted asks for a Google sign-in — one click, nothing to
> install, no approval step. The wall is the feature: a quest is private to the party
> working on it, which is what lets one teammate's discovery reach the others
> *attributed to them by name*. `scripts/check_auth_live.py` is written entirely from
> the outside to prove it holds — with no token, an unsigned token, and as a real
> signed-in stranger holding a leaked challenge id, every read is refused.

---

## 3 · Last gates, in order

- [ ] YouTube URL opens **in a private window** and plays
- [ ] `https://challengeaccepted.app` opens clean in a private window and the sign-in
      gate renders (not an error)
- [ ] Repo is public — open it signed out
- [ ] Architecture diagram attached as an image
- [ ] Category is Collaborative Partner
- [ ] All three bonus URLs pasted
- [ ] Submit

---

## Two things I would tell you before you press it

**1. The Google Cloud proof is a card, not a console screenshot.** Segment 09 shows the
`gcloud logging read` command, the service name, `us-central1`, revision
`challenge-accepted-00067-s4f`, and real log lines from the run in the video — but it is
typeset by `_video/gcpcard.py`, not captured from the Cloud Console. The rule accepts
"Google Cloud Console, Cloud Run dashboard, Vertex AI logs, URL of .run, etc", so this
is squarely inside the *etc*, and the log lines are real. But this is the exact category
that killed the last two submissions, and a screen capture of the Cloud Run dashboard is
unambiguous where a card is merely convincing.

If you want it airtight: open the Cloud Run service page and the Logs Explorer, screenshot
both, drop them in `_video/shots/` as `gcp_shot_a.png` / `gcp_shot_b.png` and say so — I
can splice them into segment 09 and re-render in about ten minutes. Optional. Your call.

### Where those three values live

Project `gen-lang-client-0955694243`. Re-verified against the Cloud Run Admin API on
20 Aug: service, region and **serving revision are unchanged since the recording**, so a
screenshot taken today matches the video frame exactly.

**Cloud Run — service, region, revision, and the `.run.app` URL, all on one page:**

```
https://console.cloud.google.com/run/detail/us-central1/challenge-accepted/revisions?project=gen-lang-client-0955694243
```

**Logs Explorer — the FORGE lines from the run in the video:**

```
https://console.cloud.google.com/logs/query;query=resource.type%3D%22cloud_run_revision%22%0Aresource.labels.service_name%3D%22challenge-accepted%22%0A%22%5BFORGE%5D%22;timeRange=2026-08-20T14:55:00Z%2F2026-08-20T15:15:00Z?project=gen-lang-client-0955694243
```

If that link drops the query, paste this into the query box by hand:

```
resource.type="cloud_run_revision"
resource.labels.service_name="challenge-accepted"
"[FORGE]"
```

**Set the time range or you will see nothing.** The forge ran
**20 Aug 2026, 15:03–15:05 UTC** — 11:03–11:05am your time. The default "Last 1 hour"
returns zero rows, which is exactly what happened to me: `gcp_evidence.py` uses a
6-hour window and now comes back empty, because the run is over eight hours old. The
logs are fine; the window was short. Retention is 30 days, so this holds until 19 Sep.

**The `.run.app` URL** is `https://challenge-accepted-xk3m7ygefa-uc.a.run.app`. The rules
name "URL of .run" as acceptable proof on its own, and it is not on screen anywhere in the
video. Adding it to the segment 09 card is a two-minute change and costs nothing.

**2. The narration is your cloned voice.** FreeClone / VoxCPM2, your voice, your script.
Nothing in the rules requires disclosing that and I would not volunteer it — but if
anyone asks, that is the answer, and it is your own likeness, so there is no rights
question.

---

*Everything else on the Stage One gate list in `docs/SUBMISSION_CHECKLIST.md` is already
ticked. This file is only the part that still needs a human.*
