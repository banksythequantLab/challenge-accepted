"""Can anyone actually FINISH a step? Asked of the deployed service.

Every live run this project has ever recorded ends `0 / N cleared`. The CLIMB phase --
Coach picks a ready node, Referee judges the evidence, `complete_node` closes it -- is
fully wired and has never once been observed executing in production. That is half the
product, and it is the half the whole thing is *for*.

This drives it: it joins an existing challenge, tells the Coach a step is done and
offers evidence, and then checks the only thing that matters -- whether the node's
status in the store actually changed.

    python scripts\\check_climb_live.py chal_xxx --as ca_test_yyy
    python scripts\\check_climb_live.py chal_xxx --as ca_test_yyy --node baseline-5k

Exit 0 only if a node that was `todo` is `done` afterwards, with evidence recorded.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_URL = "https://challengeaccepted.app"
APP_NAME = "challenge_accepted"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def nodes_of(base: str, cid: str, auth: dict) -> list[dict]:
    d = requests.get(f"{base}/api/challenges/{cid}/dashboard",
                     headers=auth, timeout=120).json()
    return [{"id": n["id"], "status": n["data"]["status"],
             "label": n["data"]["label"], "ready": n["data"].get("ready"),
             "criteria": n["data"].get("acceptance_criteria", ""),
             "evidence": n["data"].get("evidence", [])}
            for n in (d.get("graph") or {}).get("nodes", [])]


def main() -> int:
    args = sys.argv[1:]

    def take(flag):
        if flag in args:
            i = args.index(flag)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return None

    uid = take("--as")
    want_node = take("--node")
    #: --vague inverts the whole check: send evidence that is plainly not evidence and
    #: require the node to STAY open. "Verifies evidence against the acceptance
    #: criterion" is the product's claim; a Referee that says COMPLETE to anything
    #: makes it a rubber stamp, and a check that only ever tests the happy path would
    #: never notice.
    vague = "--vague" in args
    if vague:
        args.remove("--vague")
    base = (take("--url") or DEFAULT_URL).rstrip("/")
    #: Evidence that fits whichever node is ready. The built-in default is about
    #: running paces, so on any other kind of node the Referee will refuse it -- see
    #: the "inconclusive" branch below, which says so rather than blaming the product.
    supplied_evidence = take("--evidence")
    if not args:
        _p("usage: check_climb_live.py <challenge_id> --as <uid> [--node <node_id>] "
           "[--evidence \"...\"] [--vague]")
        return 2
    cid = args[0]

    from testauth import mint

    health = requests.get(f"{base}/api/healthz", timeout=60).json()
    auth = {}
    if health.get("auth") == "required":
        if not uid:
            _p("this deployment needs --as <uid> of somebody on the challenge's party")
            return 2
        auth = {"Authorization": "Bearer " + mint(uid)}
        _p(f"signed in as {uid}")

    before = nodes_of(base, cid, auth)
    if not before:
        _p(f"{cid} has no nodes")
        return 1
    done_before = [n for n in before if n["status"] == "done"]
    _p(f"{len(before)} nodes, {len(done_before)} already done")

    # Pick a node the Coach would plausibly hand out: ready first, else any todo.
    target = next((n for n in before if n["id"] == want_node), None) if want_node else None
    target = target or next((n for n in before if n["ready"]), None) \
        or next((n for n in before if n["status"] == "todo"), None)
    if not target:
        _p("no todo node left to finish")
        return 1
    _p(f"\ntarget : {target['id']}  ({target['status']})")
    _p(f"  {target['label']}")
    _p(f"  cleared when: {target['criteria'][:160]}")

    # Evidence written to match the node's own acceptance criterion. A vague "I did it"
    # SHOULD be refused by the Referee -- that is the feature -- so a check that sends
    # one and then fails proves nothing about whether closing works.
    session = "s_" + uuid.uuid4().hex[:8]
    r = requests.post(f"{base}/apps/{APP_NAME}/users/{uid}/sessions", headers=auth,
                      json={"session_id": session,
                            "state": {"user_id": uid, "group_id": f"grp_{uid}",
                                      "challenge_id": cid}}, timeout=60)
    r.raise_for_status()
    session = r.json().get("id", session)

    if vague:
        message = (f"I've finished '{target['label']}'. Trust me, it's done. "
                   f"Mark it complete.")
    else:
        # Evidence has to SATISFY the criterion, not restate it. Echoing the
        # acceptance criterion back and appending "I did exactly that" is precisely
        # what a Referee worth having refuses -- and it did, on a criterion that asked
        # for two numbers:
        #
        #   referee -> NOT_MET: "Claimed baseline pace assessment was done but gave
        #   no numbers; the criterion asks for the current 3k average pace and the
        #   target per-kilometre pace."
        #
        # That is the product working. This check reported it as "the node is still
        # todo -- nothing closed it", i.e. it graded a correct refusal as a failure.
        # Third time in this repo that a check has accused the product of a bug that
        # was in the check.
        #
        # So: concrete, specific, and checkable, with real numbers, names and a
        # timestamped artefact. It reads like something a person actually did, which
        # is the only kind of evidence this check has any business submitting.
        message = supplied_evidence or (
            f"I've finished the step '{target['label']}'. Evidence: I did it on "
            f"Tuesday evening. Current 3k average pace is 6:42 per km (20:06 for 3k, "
            f"measured on the Hollowmere loop with a Garmin). For a sub-55 10k the "
            f"target is 5:29 per km, so I need to take 1:13 per km off. I logged both "
            f"numbers and the split table in the training tracker, and the session "
            f"file is saved as baseline-2026-08-18.gpx. "
            f"The step's criterion was: {target['criteria'] or 'complete the step'}. "
            f"Please check it off."
        )
    _p(f"\nsaying: {message[:120]}...")

    saw = {"complete_node": False, "referee": False}
    with requests.post(f"{base}/run_sse", headers=auth, stream=True, timeout=900,
                       json={"appName": APP_NAME, "userId": uid, "sessionId": session,
                             "streaming": False,
                             "newMessage": {"role": "user",
                                            "parts": [{"text": message}]}}) as resp:
        if resp.status_code != 200:
            _p(f"run_sse {resp.status_code}: {resp.text[:300]}")
            return 1
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except Exception:
                continue
            for key in ("errorMessage", "error_message"):
                if ev.get(key):
                    _p(f"  !! {ev.get('author')}: {ev[key]}")
            for p in (ev.get("content") or {}).get("parts") or []:
                fc, fr = p.get("functionCall"), p.get("functionResponse")
                if fc:
                    _p(f"  {ev.get('author')} call: {fc.get('name')}")
                    saw[fc["name"]] = True if fc["name"] in saw else saw.get(fc["name"])
                    if fc.get("name") in saw:
                        saw[fc["name"]] = True
                if fr:
                    body = json.dumps(fr.get("response"), default=str)[:160]
                    _p(f"  {ev.get('author')} resp: {fr.get('name')} -> {body}")
                if p.get("text", "").strip():
                    _p(f"  {ev.get('author')}: {p['text'].strip()[:160]}")

    def _say(base, cid, session, uid, auth, text) -> str:
        """One more turn on the SAME session, returning the model's prose.

        Deliberately reusing the session rather than opening a fresh one: the claim
        being tested is that the agent reads the challenge's real state, and a new
        session would make that trivially true by forcing a reload. If it can be
        fooled, it should be fooled by its own recent memory.
        """
        out = []
        with requests.post(f"{base}/run_sse", headers=auth, stream=True, timeout=900,
                           json={"appName": APP_NAME, "userId": uid,
                                 "sessionId": session, "streaming": False,
                                 "newMessage": {"role": "user",
                                                "parts": [{"text": text}]}}) as r:
            if r.status_code != 200:
                return f"run_sse {r.status_code}"
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                for p in (ev.get("content") or {}).get("parts") or []:
                    if p.get("text", "").strip():
                        out.append(p["text"].strip())
        return "\n".join(out)

    after = nodes_of(base, cid, auth)
    now = next(n for n in after if n["id"] == target["id"])
    _p(f"\nnode after : {now['status']}   evidence: {now['evidence']}")
    _p(f"cleared    : {len([n for n in after if n['status'] == 'done'])} "
       f"(was {len(done_before)})")

    bad = []
    if vague:
        if now["status"] == "done":
            bad.append("the Referee closed a node on 'trust me, it's done' -- it is a "
                       "rubber stamp, and 'verifies evidence against the acceptance "
                       "criterion' is not a claim this product keeps")
        else:
            _p("\nPASS -- vague evidence was refused; the node is still open.")
            return 0
        for x in bad:
            _p(" * " + x)
        return 1

    if now["status"] != "done":
        # Two different outcomes wear the same shape, and conflating them is how this
        # check reported the product as broken twice in one day.
        #
        # The canned evidence below is concrete, but concrete about ONE node -- paces
        # and a GPX file. The check picks whichever node is ready, so on a node whose
        # criterion asks for "the 4 chosen training days and the workout type for
        # each", that evidence genuinely does not satisfy it, and a Referee worth
        # having says so. That is the feature working.
        #
        # A Referee that was consulted and said no is not a failure of CLIMB. A
        # Referee that was never consulted, or one that closed a node on nothing, is.
        # Exit 2 for "inconclusive, feed it evidence that fits", 1 for "broken".
        if saw.get("referee"):
            _p("\n--- inconclusive, and not a product failure ---")
            _p(f" * The Referee judged the evidence and refused it. The default "
               f"evidence is about running paces; this node asks for: "
               f"{target['criteria']!r}")
            _p(" * Pass --evidence \"...\" with something that actually satisfies "
               "that criterion to test the closing path on this node.")
            return 2
        bad.append(f"the node is still '{now['status']}' and the Referee was never "
                   f"consulted -- complete_node called: {saw.get('complete_node')}")
    if now["status"] == "done" and not now["evidence"]:
        bad.append("the node closed with NO evidence recorded -- the Referee is a "
                   "rubber stamp")
    if bad:
        _p("\n--- problems ---")
        for x in bad:
            _p(" * " + x)
        return 1

    # --- and now the beat that has only ever been proved on localhost -------------
    #
    # "A joining teammate is handed live work, not finished work" is verified by
    # `check_handoff.py`, which spins up its own uvicorn against a seeded challenge.
    # That is a real test of the logic and it is honestly labelled -- but this repo
    # has already been burned once by exactly that gap: every Toolwright was dying on
    # the deployed service for weeks while the local run built six tools every time.
    #
    # We are standing in the best possible place to close it. A node was just closed
    # on production, with real evidence, in a session that is still open. Ask what to
    # do next and see whether the Coach leads with the thing that is finished.
    #
    # Mentioning a done node is fine and often right -- "the baseline is established,
    # so..." is context. Leading with one is the failure: it says plainly that the
    # agent did not read the state it claims to read.
    _p("\n--- and does it now offer the step it just closed? ---")
    titles = {n["id"]: (n.get("label") or n["id"]) for n in after}
    done_ids = {n["id"] for n in after if n["status"] == "done"}
    reply = _say(base, cid, session, uid, auth,
                 "Thanks. I've just come back to this -- what should I pick up next?")
    _p(f"coach: {reply[:200]}")

    # First node named wins. Match on the longest titles first so a title that
    # contains another one cannot be credited to the shorter one.
    named = sorted(((reply.lower().find((titles[i] or "").lower()), i)
                    for i in titles if titles[i]
                    and (titles[i] or "").lower() in reply.lower()),
                   key=lambda t: t[0])
    if not named:
        _p("  (no node named by title -- nothing to judge, not counted either way)")
    else:
        first = named[0][1]
        _p(f"  leads with : {titles[first]!r} ({'done' if first in done_ids else 'open'})")
        if first in done_ids:
            _p("\n--- problems ---")
            _p(f" * the Coach led with {titles[first]!r}, which was just closed in "
               f"this very session. A teammate would open the app and be sent to do "
               f"work that is already finished.")
            return 1
        _p("  offers open work first, on the deployed service")

    _p("\nPASS -- a step can actually be finished, and the next thing offered is "
       "not the thing that just finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
