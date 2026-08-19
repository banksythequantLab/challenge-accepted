# Submission checklist — All Things Agentic, Collaborative Partner

**Deadline: 31 Aug 2026, 5:00pm PT.** Judging 1 Sept – 1 Oct. Winners 8 Oct.

Two previous videos were rejected for *failing to follow directions and include a demo
of use*. That is a **content** failure, not a production-quality one — so this file is
a list of things a judge can tick, taken from the rules verbatim, not a style guide.

Tick it against the finished artefacts, not against intentions.

---

## Stage One — pass/fail viability

Every one of these is a hard gate. Missing any is elimination before anything is scored.

| # | Requirement | Status |
|---|---|---|
| 1 | **Hosted project link** — "a URL to the hosted Project … for judging and testing" | ☐ `https://challengeaccepted.app` |
| 2 | **Text description** — features, functionality, technologies, data sources, learnings | ☑ `docs/DEVPOST.md`, accuracy pass done — still has to be **pasted into the form** |
| 3 | **Code repository** — public, or share with `testing@devpost.com` and `cloudhackathons@google.com` | ☐ public at `banksythequantLab/challenge-accepted` — confirm it is current |
| 4 | **Architecture diagram** — "a clear visual representation of your system" | ☑ `docs/architecture.png` |
| 5 | **Demonstration video** — see below | ☐ |
| 6 | **Gemini 3.5 or newer** | ☑ `gemini-3.6-flash` + `gemini-3.5-flash-lite`, both live |
| 7 | **A Google agent framework** (ADK / GenAI SDK / Antigravity / GenKit) | ☑ Google ADK (Python) |
| 8 | **A Google Cloud infra service** (Cloud Run / Cloud SQL / Firestore / GKE / Pub-Sub) | ☑ Cloud Run + Firestore |
| 9 | **One category selected** | ☐ Collaborative Partner |
| 10 | **Free and unrestricted for judges until judging ends** | ⚠ see *The sign-in wall* below |
| 11 | **Spin-up instructions in `README.md`** — listed in the requirements alongside the repo link, and scored again under Demo & Production Readiness ("setup reproducibility") | ☑ `README.md` — local run and `deploy\deploy.ps1`. Worth one cold read by someone who has never run it |

---

## The video — where the last two died

Rules text, quoted:

- **"It should not be longer than 4 minutes. If it is longer than 4 minutes, only the
  first 4 minutes may be evaluated."**
- **"Submission must be uploaded to and made publicly visible on YouTube or Vimeo."**
- Must include **"a short overview of the problem your Project is solving, the value
  proposition as well as a demo of the application in action"**
- Must **"demonstrate the backend is running on Google Cloud"**
- Must **"be in English or include English subtitles"**
- No third-party advertising or sponsorship indicators; nothing derogatory; no IP you
  do not own.

### Tick these against the finished cut

| ✓ | Item | Why it is here |
|---|---|---|
| ☐ | Under 4:00, checked on the uploaded file, not the timeline | The cap is on what they watch |
| ☐ | Public on YouTube or Vimeo — open it in a private window | "Unlisted" is not "publicly visible"; a private link scores zero |
| ☐ | States **the problem** out loud in the first 30s | Explicitly required, and easy to skip when you are proud of the build |
| ☐ | States **the value proposition** | Separate requirement from the problem. Both, not one |
| ☐ | Shows **the application in action** — a person using it, not slides | This is the one the rejections named |
| ☐ | **Google Cloud is visibly on screen** — Cloud Run console, or the `.run.app` / deployed URL in the address bar | Explicitly required. Free marks. Most commonly missed |
| ☐ | English, or English subtitles burned in or uploaded | |
| ☐ | No music you do not have rights to, no brand logos other than your own | |

### Scored separately (not pass/fail)

> *"Does the video show an unedited, live execution of the agent performing its task?"*
> — one sub-point inside **Demo & Production Readiness (30%)**.

Cutting a wait is **not** against the rules and does not disqualify anything. It costs
some fraction of one sub-criterion. A visible, labelled jump — `⏱ 3:48 elapsed` on
screen — reads as confident rather than evasive.

**Measured runtimes, warm, revision 00063** (so the cut can be planned rather than
discovered):

| beat | time |
|---|---|
| 3 interview turns | 40s |
| Cartographer | 27s |
| Quartermaster | 17s |
| FORGE, 8 workers, 6 specs, one batch | 3m 48s |
| **cold start to finished toolkit** | **~5m 16s** |

A full unbroken run does not fit in four minutes. FORGE is most of it, and the two
levers available have been spent — see `config.FORGE_WORKERS` and
`config.MODEL_TOOLWRIGHT`.

### Before recording — non-negotiable

- [ ] **Deploy with `-KeepWarm`** (`min-instances=1`). On a cold instance one run spent
      **nine minutes** between Cartographer and the first FORGE dispatch, against 46s
      warm. You cannot edit around that; you would just re-record and not know why.
- [ ] Rehearse the full run end to end at least twice on the revision you will record.
- [ ] Check the party roster on the demo challenge — live checks leave `ca_test_*`
      identities behind, and `6 on this quest — you and Forge Dc53A6, Dana B71C22…`
      makes a two-person party look like a load test. `python scripts\reap_test_users.py`.

---

## Judging criteria — what the score is actually made of

| Weight | Criterion | What it asks |
|---|---|---|
| 40% | Innovation & Operational Utility | "Does the system eliminate real-world friction? Is the 'Twist' present?" Autonomous execution over chat |
| 30% | Architectural Discipline & Tech Stack | Engineering decisions, decoupling, state management, failure tolerance, modularisation, security isolation |
| 30% | Demo & Production Readiness | Documentation clarity, the unedited-live-execution question, repo quality and setup reproducibility |

Stage Three bonus, **max +0.6 on a 1–6 scale**. **All three earned: +0.6.** Quoted from
the rules page rather than paraphrased, because the first version of this section
paraphrased it and got the hashtag wrong — see the warning below.

Every one of them is *published* and none of them is *claimed* until the three URLs are
in the submission form. That is the whole remaining task for this section.

- [x] **Published content: +0.2 — PUBLISHED.**
      <https://gist.github.com/banksythequantLab/d1b85fd03719542f72341bd69d9077aa>

      *"Publish a piece of content (blog, podcast, video): Covering how the project was
      built on any public platform."* Two conditions that are easy to miss and are
      worth the whole 0.2 on their own: *"The content must be public (not unlisted)"*
      and *"You must include language that says you created the piece of content for
      the purposes of entering this hackathon."* Both are satisfied — public confirmed
      by fetching the gist API **without** an auth header (`"public": true`), and the
      required sentence is the opening paragraph, not a footnote.
      Source: `docs/BUILD_WRITEUP.md`.

      ☐ **Still to do: paste that URL into the submission form.** Publishing it is not
      claiming it.

- [x] **Social post: +0.2 — POSTED.**
      <https://x.com/banksythequant/status/2090201173580001327>

      *"Publish a social media post: Highlight or promote your project on social media
      post on X, LinkedIn, Instagram, or Facebook."* Posted from `@banksythequant`, the
      same account that announced the DeveloperWeek NY 2026 prize, so the hackathon
      history is on one timeline.

      The tag **rendered as a real hashtag link** —
      `href="/hashtag/AllThingsAgenticHackathon?src=hashtag_click"` — which is the
      thing actually worth checking. Plain grey text means X did not register it, and a
      tag that did not register is a bonus that did not land.

      > ⚠️ This file previously said the tag was `#AllThingsAgentic`. It is not.
      > A post with the short tag is a post that scores zero for this bonus while
      > looking, to whoever wrote it, exactly like a post that scored 0.2. Copy the
      > tag from `docs/SOCIAL_POST.md`; do not retype it.

      Note: the published text is a 280-character cut of the drafts, because the
      account is not on Premium. The long-form versions in `docs/SOCIAL_POST.md` are
      still the right copy for LinkedIn if a second post is ever wanted — one link is
      enough for the 0.2, a second only buys a spare.

      ☐ **Still to do: paste that URL into the submission form.**

- [x] **Additional Google AI models: +0.2 each, max +0.6.** *"Earn 0.2 bonus points
      for each additional Google AI model successfully integrated (such as Gemma, Veo,
      or Lyria), up to a maximum of 0.6 total bonus points."*

      **Gemma 4 is integrated and live: +0.2 claimed.** The Archivist runs on
      `gemma-4-26b-a4b-it-maas`. Evidence a judge can check without taking our word:
      `https://challengeaccepted.app/api/healthz` names the serving model per tier.
      Proved end to end on the deployed service — `scripts/check_archivist_model.py`
      (tool calls, not prose) and `scripts/check_party_live.py` (a teammate inherited
      a fact Gemma recorded). Reasoning is in `config.MODEL_ARCHIVIST`.

      **The other two are not being chased, and that is a decision rather than a
      shortfall.** Veo and Lyria have no job in a goal-decomposition app. Bolting video
      or music generation onto it to collect +0.2 would put a visible bolt-on in front
      of the 30% *Architectural Discipline* criterion, whose whole subject is scope
      control — and this submission's argument there is a deliberately **closed**
      seven-type tool taxonomy. Trading a credible hit on 30% for a possible 0.2 is a
      bad trade. `gemini-embedding-001` is also in production for fact ranking, but it
      is a Gemini model rather than an "additional" one, so it is not claimed either.

Source: <https://allthingsagentichackathon.devpost.com/rules>

---

## The sign-in wall

> *"The Entrant must make the Project available free of charge and without any
> restriction, for testing, evaluation and use by the Sponsor, Administrator and
> Judges until the Judging Period ends."*

`challengeaccepted.app` requires Google sign-in. A judge **can** sign in, so this is
probably compliant — but a judge who bounces at the wall scores the submission on
nothing at all, and "without any restriction" is the phrase to be nervous about.

**Decided: keep the wall.** It is not incidental, it is load-bearing:

1. **Identity is what makes the collaboration claim possible.** No accounts means no
   roster, no attribution (*"Derek found that Cloud Run needs billing"* — by name), no
   personal-vs-shared tool state, no leaving a party, no revocable invites. The demo's
   central beat is a teammate inheriting a discovery credited to a specific person.
   Anonymously that is a text blob.
2. **Turning auth off serves an admin console.** `main.py`: `web=not auth.required()`.
   With auth off, ADK's dev UI is exposed — and it runs agents as any user id typed
   into it.
3. **It is scoring evidence.** "Security isolation" is named in the 30% Architectural
   Discipline criterion, and `scripts\check_auth_live.py` is the only check written
   entirely from the outside — every assertion is something that must FAIL. A signed-in
   stranger holding a leaked challenge id gets 403 on the dashboard, tools and journal.
4. **Cost and abuse.** ~$0.86 of model calls per challenge and no rate limiting. An open
   `/run_sse` is somebody else's bill.

A read-only demo challenge was rejected: real engineering, it weakens the isolation
story being scored, and it solves a problem two sentences solve.

### What was done instead

- [x] **The gate now sells.** It used to explain the wall without saying what was behind
      it — answering "why are you asking" for somebody not yet given a reason to care.
      It now leads with the Warden's own opening line, so a judge reads the promise on
      the door and the product makes good on it one screen later. Verified rendering at
      1280px and 390px.
- [ ] **Say it in the description.** Ready to paste:

> **Signing in.** Challenge Accepted asks for a Google sign-in — one click, nothing to
> install, no approval step. The wall is the feature: a quest is private to the party
> working on it, which is what lets one teammate's discovery reach the others
> *attributed to them by name*. `scripts/check_auth_live.py` is written entirely from
> the outside to prove it holds — with no token, an unsigned token, and as a real
> signed-in stranger holding a leaked challenge id, every read is refused.

---

## Disqualification triggers, quoted

- False information about identity, address, contact, ownership of rights, or compliance
- **Pre-existing projects, or work developed outside the submission period**
  (3 Aug – 31 Aug 2026)
- Plagiarism or IP infringement
- Failing the content restrictions or the theme
- Ineligibility (sanctioned countries, employees of contest entities)

---

## Final pass, on submission day

- [ ] Hosted link opens clean in a private window on a machine that has never seen it
- [ ] Repo `main` is pushed and matches the deployed revision
- [ ] `README.md` claims match what the checks actually prove — every "Verified live"
      row re-run against the revision being submitted
- [ ] Architecture diagram attached as an **image**, not a link to an HTML file
- [ ] Video URL opens in a private window and plays
- [ ] Category set to **Collaborative Partner**
- [ ] Submitted with a **day** of slack, not an hour
