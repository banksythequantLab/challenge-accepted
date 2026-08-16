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
    if not args:
        _p("usage: check_climb_live.py <challenge_id> --as <uid> [--node <node_id>]")
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
        message = (
            f"I've finished the step '{target['label']}'. Here is my evidence: "
            f"{target['criteria'] or 'I completed it'} -- I did exactly that today and "
            f"wrote the result down. Please check it off."
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
        bad.append(f"the node is still '{now['status']}' -- nothing closed it. "
                   f"complete_node called: {saw.get('complete_node')}")
    if now["status"] == "done" and not now["evidence"]:
        bad.append("the node closed with NO evidence recorded -- the Referee is a "
                   "rubber stamp")
    if bad:
        _p("\n--- problems ---")
        for x in bad:
            _p(" * " + x)
        return 1
    _p("\nPASS -- a step can actually be finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
