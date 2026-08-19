"""Can a party actually keep ONE record -- and can a save refuse to clobber a teammate's?

Two users, two browsers, one tool, over real HTTP with real tokens:

  1. Dana saves into a SHARED tool. Derek opens it and sees her numbers.
  2. Derek is told the scope and who last touched it, not left to guess.
  3. Dana saves into a PERSONAL tool on the same challenge at the same moment.
     Derek sees nothing. The default has not moved.
  4. Both hold version N. Dana saves first and wins. Derek's save is REFUSED with 409
     and handed the winning state, so his client can name her rather than say
     "something happened".
  5. Derek reloads, redoes his edit on top, and it lands.
  6. A stranger is still 403 on all of it. Shared means shared with the PARTY.

What this check does NOT prove: that the Quartermaster marks the right tools shared.
That is a judgement call by a model on a real graph, and pinning it here would mean
asserting on model output. The scope flag's provenance is pinned in
tests/test_shared_spec_flag.py; this drives the wire.

    python scripts\\check_shared_tool_live.py https://challengeaccepted.app

Seeds its own challenge and tools through the store and deletes them at the end, so it
does not need a FORGE run to have happened to produce a shared tool -- and does not
leave one behind. Costs nothing: it never runs an agent turn.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_URL = "https://challengeaccepted.app"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main(base: str) -> int:
    base = base.rstrip("/")
    from testauth import PREFIX, mint, require_shared_store

    from challenge_accepted.services.store import store

    # The target being on Firestore is checked below. This checks the other end: that
    # THIS process seeds into the same one, rather than into the in-memory fallback
    # `Store` uses when GOOGLE_CLOUD_PROJECT is unset.
    require_shared_store(base)

    health = requests.get(f"{base}/api/healthz", timeout=60).json()
    _p(f"target : {base}")
    _p(f"health : store={health.get('store')} auth={health.get('auth')}")
    if health.get("auth") != "required":
        _p("auth is off here -- every permission row below would pass trivially, so "
           "this stops rather than printing meaningless ticks.")
        return 1
    if health.get("store") != "firestore":
        _p("this deployment is on the in-memory store, so 'Derek sees what Dana wrote' "
           "would only prove they hit the same process. Stopping.")
        return 1

    tag = uuid.uuid4().hex[:6]
    derek = PREFIX + "sh_derek_" + tag
    dana = PREFIX + "sh_dana_" + tag
    stranger = PREFIX + "sh_out_" + tag
    D = {"Authorization": "Bearer " + mint(derek)}
    A = {"Authorization": "Bearer " + mint(dana)}
    X = {"Authorization": "Bearer " + mint(stranger)}
    bad: list[str] = []

    def check(label: str, got, want) -> None:
        ok = got == want
        _p(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
        if not ok:
            bad.append(label)

    gid = "grp_shared_check_" + tag
    cid = store.create_challenge({"outcome": "shared tool state check"},
                                 owner_id=derek, group_id=gid)
    store.join_group(gid, derek)
    store.join_group(gid, dana)
    store.put_user(dana, {"name": "Dana"})
    store.put_node(cid, {"id": "split", "title": "Split the costs",
                         "acceptance_criteria": "x", "depends_on": []})
    shared = store.put_tool(cid, "split", {
        "type": "mini_app", "name": "Cost Split", "source": "<html></html>",
        "usage": "u", "smoke_test_passed": True, "degraded": False, "shared": True})
    personal = store.put_tool(cid, "split", {
        "type": "tracker", "name": "My Hours", "source": "<html></html>",
        "usage": "u", "smoke_test_passed": True, "degraded": False, "shared": False})
    _p(f"seeded : {cid}  shared={shared}  personal={personal}")

    def get(who, tid):
        return requests.get(f"{base}/api/challenges/{cid}/tools/{tid}/state",
                            headers=who, timeout=60)

    def put(who, tid, state, version=None):
        body = {"state": state}
        if version is not None:
            body["version"] = version
        return requests.put(f"{base}/api/challenges/{cid}/tools/{tid}/state",
                            headers=who, json=body, timeout=60)

    try:
        _p("\n1. one record for the party")
        check("dana saves", put(A, shared, {"total": "120"}).status_code, 200)
        seen = get(D, shared).json()
        check("derek reads dana's numbers", seen["state"], {"total": "120"})
        check("derek is told it is shared", seen["shared"], True)
        check("derek is told who saved it", seen["updated_by"], "Dana")

        _p("\n2. personal stays personal, same challenge, same moment")
        check("dana saves her own log", put(A, personal, {"hours": "12"}).status_code, 200)
        check("derek sees none of it", get(D, personal).json()["state"], {})

        _p("\n3. a stale save is refused, not applied")
        held = get(D, shared).json()["version"]
        check("dana saves again", put(A, shared, {"total": "150"}, held).status_code, 200)
        late = put(D, shared, {"total": "0"}, held)
        check("derek's stale save", late.status_code, 409)
        detail = (late.json() or {}).get("detail") or {}
        check("...names her", detail.get("updated_by"), "Dana")
        check("...hands back the winner", detail.get("state"), {"total": "150"})
        check("dana's number survived", get(D, shared).json()["state"], {"total": "150"})

        _p("\n4. reload, redo, land")
        now = get(D, shared).json()["version"]
        check("derek saves on top", put(D, shared, {"total": "175"}, now).status_code, 200)
        check("dana sees his", get(A, shared).json()["state"], {"total": "175"})

        _p("\n5. shared means shared with the PARTY")
        check("stranger on the shared tool", get(X, shared).status_code, 403)
        check("stranger writing to it", put(X, shared, {"total": "0"}).status_code, 403)
    finally:
        # Leave nothing behind. A check that seeds production and walks away turns the
        # next person's dashboard into a graveyard of test quests.
        for tid in (shared, personal):
            for uid in (derek, dana):
                store.delete("tool_state", store.tool_state_key(tid, uid, False))
            store.delete("tool_state", store.tool_state_key(tid, "", True))
            store.delete("tools", tid)
        store.delete("nodes", f"{cid}:split")
        store.delete("groups", gid)
        store.delete("challenges", cid)
        # The profile too. `put_user` above is what makes "last saved by Dana" a real
        # assertion rather than a uid comparison, and a check that writes a user
        # document into production and leaves it there is how `reap_test_users.py`
        # came to exist in the first place.
        store.delete("users", dana)
        _p(f"\ncleaned: {cid}")

    if bad:
        _p(f"\nFAIL: {len(bad)} -- " + "; ".join(bad))
        return 1
    _p("\nPASS: a party keeps one copy, a person keeps their own, and a save that "
       "would overwrite a teammate's is refused with theirs attached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
