# Social post drafts — the +0.2 bonus

The rule, quoted:

> *"Publish a social media post: Highlight or promote your project on social media post
> on X, LinkedIn, Instagram, or Facebook."*
>
> *"For any social media posts on platforms such as X or LinkedIn, include the hashtag
> **#AllThingsAgenticHackathon**."*

Then paste the post's URL into the submission form. One qualifying post is enough for
the full 0.2; posting on both X and LinkedIn does not pay twice, it just gives you a
spare link if one gets rate-limited or shadow-filtered.

> ⚠️ **Copy the hashtag from this file. Do not retype it.**
> `#AllThingsAgenticHackathon`
> An earlier version of the checklist in this repo said `#AllThingsAgentic`. A post
> with the short tag scores zero for this bonus and looks, to whoever wrote it, exactly
> like a post that scored 0.2.

Attach `docs/architecture.png`, or a screenshot of the quest map mid-FORGE with tools
landing on nodes. The map is the thing that makes people stop scrolling; a screenshot
of a chat window is not.

---

## X — option A (the premise)

> Every AI I asked for help with a goal gave me a plan. Twelve numbered steps. I did
> none of them — because each step still needed a tool I didn't have.
>
> So I built the thing that makes the tools.
>
> Challenge Accepted: 9 agents on Google ADK. It interviews you, draws a dependency
> graph of your goal, then writes and smoke-tests a real tool for every node —
> calculators, trackers, drills, small web apps — and coaches you through one step at a
> time.
>
> Live: https://challengeaccepted.app
> Code: https://github.com/banksythequantLab/challenge-accepted
>
> #AllThingsAgenticHackathon

## X — option B (the engineering hook)

> Spent days chasing a bug where 6 tool specs became 1 tool, with no error anywhere.
> Halving the worker count made it better. Three times running.
>
> That's what a race looks like AND what a narrowed window looks like. So I stopped
> guessing and wrote a flow tracer that logs every agent's ADK branch. Answer, first
> run:
>
> branch=cartographer@call_636196.forge_workers.toolwright_0
>
> The whole build phase was running inside a sub-agent's frame, and dying when that
> tool call returned. Two lines fixed it.
>
> Challenge Accepted — 9 agents that build the tools your goal actually needs.
> https://challengeaccepted.app
>
> #AllThingsAgenticHackathon

---

## LinkedIn

> **I stopped asking AI for a plan and built something that hands me the tools instead.**
>
> Every assistant I asked for help with a goal gave me twelve sensible numbered steps.
> I did none of them. Each step still needed something I didn't have — a spreadsheet
> model, a checklist, a comparison of four vendors, a practice set.
>
> The plan was never the missing piece. The tools were.
>
> **Challenge Accepted** is nine agents on Google ADK that:
>
> • interview you until the goal is checkable by a stranger
> • decompose it into a dependency graph of two-hour tasks, each with a written
>   acceptance criterion
> • ask "what tool would make this step trivial?" for every node — then write it, run
>   it, smoke-test it, and attach it
> • coach you through one ready step at a time, checking evidence against the criterion
>
> It's collaborative: invite a teammate and their coach opens with what you already
> discovered, attributed to you by name. Eight tool builders run in parallel; a shared
> cost split is one record for the party, a training log is yours alone.
>
> Built on Google ADK, Gemini 3.6 Flash, Cloud Run, Firestore and Vertex AI Memory
> Bank. The honest part of the story is in the write-up: three stacked bugs meant the
> deployed service built zero tools for weeks while every local run worked and my own
> README recorded it as verified. What found it was refusing to read silence as success.
>
> Live: https://challengeaccepted.app
> Code and full write-up: https://github.com/banksythequantLab/challenge-accepted
>
> #AllThingsAgenticHackathon

---

## After posting

- [ ] Post is **public**, not followers-only or connections-only — open it in a private
      window before pasting the link anywhere.
- [ ] The hashtag renders as a link in the published post, not as plain text.
- [ ] URL pasted into the Devpost submission form.
