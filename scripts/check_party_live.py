"""Two people, one challenge, on the DEPLOYED service.

This is the beat the Collaborative Partner submission rests on, and the one that goes on
camera at 2:20 in `docs\\DEMO_SCRIPT.md`: a teammate opens an invite link and is met by
what the first person already discovered, attributed, without being re-interviewed.

`check_party.py` proves it -- against a local server. So did every FORGE check, for
weeks, while the deployed service built nothing at all. The gap between those two
sentences is the entire reason this file exists.

What it asserts, in the order a judge would see it:

  1. Derek opens a challenge and the agents record a discovery as a group fact.
  2. Dana arrives with a DIFFERENT user id, no group, and only the challenge id -- which
     is exactly what an invite link carries.
  3. Dana's first reply repeats Derek's discovery. Nothing else could have told her.
  4. Dana is pointed at an OPEN node, not congratulated on finished ones.
  5. Dana's own private group is still empty -- her arrival must not fork the party.

    python scripts\\check_party_live.py https://challengeaccepted.app

Exit 0 only if a stranger inherits the party's knowledge on the deployed service.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import uuid

APP = "challenge_accepted"
DEFAULT_URL = "https://challengeaccepted.app"

#: Distinctive enough that a model inventing plausible filler cannot land on it, and
#: phrased as something only a person doing the work would find out.
DISCOVERY = ("I found out the hard way that Cloud Run needs billing enabled and nobody "
             "on our team has GCP admin, so hosting has to go through Vercel instead.")

DEREK_TURNS = [
    "I want to launch a small web app for a hackathon by the end of the month.",
    "It is a two-person team, we have evenings only, and neither of us has shipped "
    "anything to production before.",
    DISCOVERY,
    "That's everything -- accept the challenge and draw me the map.",
]

DANA_ASKS = "I just joined. What should I pick up, and what do I need to know?"


def _post(base, path, body, timeout=600):
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _get(base, path, timeout=90):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=timeout) as r:
        return json.load(r)


def _session(base, user, state):
    sid = "s_" + uuid.uuid4().hex[:10]
    _post(base, f"/apps/{APP}/users/{user}/sessions",
          {"session_id": sid, "state": state}, timeout=90)
    return sid


def _say(base, user, sid, text):
    """One turn. Returns (all model text, tool calls seen)."""
    raw = _post(base, "/run_sse", {
        "app_name": APP, "user_id": user, "session_id": sid,
        "new_message": {"role": "user", "parts": [{"text": text}]},
        "streaming": False,
    })
    said, calls = [], []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        for part in (ev.get("content") or {}).get("parts") or []:
            if part.get("text"):
                said.append(f"{ev.get('author','?')}: {part['text']}")
            if part.get("functionCall"):
                calls.append(f"{ev.get('author','?')}->{part['functionCall'].get('name')}")
    return "\n".join(said), calls


def main(base: str) -> int:
    base = base.rstrip("/")
    derek = f"derek_{uuid.uuid4().hex[:8]}"
    dana = f"dana_{uuid.uuid4().hex[:8]}"

    health = _get(base, "/api/healthz")
    print(f"target : {base}")
    print(f"health : store={health.get('store')} memory={health.get('memory')}")
    print(f"derek  : {derek}\ndana   : {dana}\n")

    # --- Derek opens the challenge and tells the agents something real -----------
    print("--- derek ---")
    d_sid = _session(base, derek, {"user_id": derek, "group_id": f"grp_{derek}"})
    for text in DEREK_TURNS:
        print(f">>> {text[:72]}")
        said, _ = _say(base, derek, d_sid, text)
        print(f"    ...{len(said)} chars")

    state = _get(base, f"/apps/{APP}/users/{derek}/sessions/{d_sid}").get("state") or {}
    cid, gid = state.get("challenge_id"), state.get("group_id")
    print(f"\nchallenge : {cid}\ngroup     : {gid}")
    if not cid:
        print("\nFAIL: Derek never got a challenge, so there is no party to join.")
        return 1

    dash = _get(base, f"/api/challenges/{cid}/dashboard")
    summary = dash.get("summary") or {}
    facts = summary.get("group_facts") or []
    charter = summary.get("charter") or {}
    # Status lives in `data`, like the label. Reading it from the top level silently
    # matched nothing and left `open_nodes` empty, which then made the node assertion
    # unevaluable -- the third variant of the same mistake in one file.
    def _open(graph):
        out = []
        for n in graph:
            status = (n.get("data") or {}).get("status") or n.get("status")
            if status not in ("done", "superseded"):
                out.append(n)
        return out

    nodes = (dash.get("graph") or {}).get("nodes") or []
    open_nodes = _open(nodes)
    print(f"nodes     : {len(nodes)} ({len(open_nodes)} open)")

    # Where a discovery lands depends on WHEN it is said, and the first version of this
    # check did not know that. Said during ACCEPT it goes into the charter, because the
    # Interviewer holds no `remember_group_fact` -- that tool is on Warden, the Coach
    # and the Archivist, which is to say the CLIMB phase. Said during CLIMB it becomes a
    # group fact. Both channels reach a teammate through `read_challenge_state`.
    #
    # So failing on `group_facts == 0` was asserting the mechanism instead of the
    # promise, and would have reported a working product as broken. What matters is
    # whether Dana ends up knowing what Derek found out.
    blob = json.dumps({"facts": facts, "charter": charter}).lower()
    channel = ("group facts" if facts else
               "the charter" if "vercel" in blob else None)
    print(f"facts     : {len(facts)}")
    print(f"discovery : recorded in {channel or 'NOWHERE'}")
    for line in (charter.get("constraints") or [])[:4]:
        print(f"   - {line[:96]}")
    if channel is None:
        print("\nFAIL: Derek's discovery was not recorded anywhere a teammate can read "
              "it -- not as a group fact, not in the charter. The beat cannot work.")
        return 1


    # --- Dana arrives with nothing but the challenge id -------------------------
    # No group_id. That is the whole point: the invite link carries the challenge, and
    # the server must work out the party from it. Handing her the group here would be
    # testing our own fixture instead of the product.
    print("\n--- dana (new user, invite link only) ---")
    a_sid = _session(base, dana, {"user_id": dana, "challenge_id": cid})
    said, calls = _say(base, dana, a_sid, DANA_ASKS)
    print(f">>> {DANA_ASKS}")
    print(f"    tool calls: {calls}\n")
    print(said[:1100])

    # Re-read the graph AFTER her turn. The Cartographer can still be drawing when
    # Derek's request returns, and a check that reads too early reports zero nodes and
    # then cannot evaluate its own assertion.
    open_nodes = _open((_get(base, f"/api/challenges/{cid}/dashboard")
                        .get("graph") or {}).get("nodes") or [])

    low = said.lower()
    failures = []

    # 1. Did Derek's discovery reach her?
    #
    # One word carries this, not three. "Vercel" is the operative fact -- Derek chose it
    # because Cloud Run was blocked, and Dana has no other way to know it. "billing" and
    # "admin" are the reasoning, which a model may or may not restate; demanding two of
    # three was testing phrasing, and failed a run whose reply plainly said Vercel.
    print(f"\ninherited 'vercel' : {'vercel' in low}")
    print(f"also mentioned     : {[w for w in ('billing','admin','cloud run') if w in low]}")
    if "vercel" not in low:
        failures.append("Dana did not inherit Derek's discovery -- the one thing the "
                        "Collaborative Partner claim rests on")

    # 2. Was she pointed at work, rather than re-interviewed?
    #
    # The first version read `n["title"]`, which does not exist -- the graph endpoint
    # returns `{id, position, data}` and the title lives in `data`. So it collected
    # `[None, None, None]`, which is a truthy list, and PASSED. Three vacuous passes in
    # one day is a pattern, not bad luck: an assertion that cannot fail is worse than
    # no assertion, because it also tells you it checked. Titles are filtered for
    # truthiness now, and a run that finds no titles at all fails loudly.
    # The key is `data.label`, not `title` -- confirmed by reading the payload rather
    # than assuming a third time. The node id counts as a name too: the agents quote it
    # verbatim (`verify-vercel-account-and-repo`) when they hand work over.
    titles = []
    for n in open_nodes:
        label = (n.get("data") or {}).get("label")
        if label:
            titles.append(label)
        if n.get("id"):
            titles.append(str(n["id"]).replace("-", " "))
    if not titles:
        failures.append("no open node has a readable label or id -- this check cannot "
                        "tell whether Dana was pointed at work, so it must not claim to")
    named = [t for t in titles if t.lower() in low]
    print(f"open node named : {named[:3] or 'NONE'}  (of {len(titles)} candidates)")
    if titles and not named:
        failures.append("Dana was not pointed at any open node by name")

    # 3. Did her arrival fork the party into a private group of one?
    solo = _get(base, f"/api/challenges?group_id=grp_{dana}&limit=5")
    solo = solo if isinstance(solo, list) else solo.get("challenges", [])
    print(f"dana's own group: {len(solo)} challenge(s)  <- must be 0")
    if solo:
        failures.append(f"Dana was forked into her own group with {len(solo)} challenge(s)")

    # 4. Is the roster actually two people now?
    party = (_get(base, f"/api/challenges/{cid}/dashboard").get("summary") or {}).get("party") or []
    print(f"party roster    : {len(party)} -> {party}")
    if len(party) < 2:
        failures.append(f"the roster still reads {len(party)} after a teammate joined")

    if failures:
        print("\n--- FAILURES ---")
        for f in failures:
            print(" * " + f)
        return 1

    print("\nPASS: a stranger with an invite link inherited the party's knowledge and "
          "was handed live work, on the deployed service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
