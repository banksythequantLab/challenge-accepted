"""Can a teammate actually get out, on the DEPLOYED service?

The membership wall is only half a claim. `check_auth_live.py` proves a stranger cannot
get IN; this proves somebody who is in can get OUT, and that leaving revokes access for
real rather than just editing a roster on a screen.

That distinction is the whole point. A "leave" that removes your name but leaves the
dashboard readable is the same failure as a logout that keeps the session alive: it
tells the user something happened when nothing did, and it is invisible from the UI
because the UI is exactly what stopped showing you.

Six things, in the order a person would experience them:

  1. Dana joins Derek's quest with nothing but the id, and can read it.
  2. Dana leaves. Her own request, her own identity.
  3. Dana is refused the dashboard, the tools and the journal -- 403, not 404.
  4. The quest is gone from Dana's list, so it will not reappear in her picker.
  5. Derek's roster is back to one, and what Dana discovered is still on it.
  6. A member cannot remove somebody else, and nobody can remove the owner.

    python scripts\\check_party_exit_live.py https://challengeaccepted.app

Exit 0 only if leaving is real. Costs nothing -- it never runs an agent turn.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_URL = "https://challengeaccepted.app"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main() -> int:
    args = list(sys.argv[1:])
    base = DEFAULT_URL
    if args and args[0].startswith("http"):
        base = args.pop(0)
    base = base.rstrip("/")
    if not args:
        _p("usage: check_party_exit_live.py [url] <challenge_id> --owner <uid>")
        return 2
    cid = args[0]
    owner = args[args.index("--owner") + 1] if "--owner" in args else None

    from testauth import PREFIX, mint

    health = requests.get(f"{base}/api/healthz", timeout=60).json()
    if health.get("auth") != "required":
        _p("auth is off on this deployment -- every permission below passes trivially, "
           "so the check stops rather than printing a row of meaningless ticks.")
        return 1

    if not owner:
        _p("--owner is required: this check acts as the person who started the quest, "
           "and guessing at that is how you write a test that grades its own homework.")
        return 2

    dana = PREFIX + "leave_" + uuid.uuid4().hex[:6]
    third = PREFIX + "third_" + uuid.uuid4().hex[:6]
    D = {"Authorization": "Bearer " + mint(dana)}
    O = {"Authorization": "Bearer " + mint(owner)}
    T = {"Authorization": "Bearer " + mint(third)}
    bad: list[str] = []

    def show(label: str, got: int, want) -> None:
        want = want if isinstance(want, tuple) else (want,)
        ok = got in want
        _p(f"  {'ok  ' if ok else 'FAIL'}  {got:<4} {label}")
        if not ok:
            bad.append(f"{label}: got {got}, expected {'/'.join(map(str, want))}")

    _p(f"target   : {base}\nchallenge: {cid}\nowner    : {owner}\ndana     : {dana}\n")

    _p("1. dana joins with nothing but the id:")
    show("POST .../join",
         requests.post(f"{base}/api/challenges/{cid}/join", headers=D,
                       json={"user_id": dana}, timeout=60).status_code, 200)
    show("GET  .../dashboard  (she can read it now)",
         requests.get(f"{base}/api/challenges/{cid}/dashboard",
                      headers=D, timeout=60).status_code, 200)

    _p("\n2. a member cannot remove another member:")
    requests.post(f"{base}/api/challenges/{cid}/join", headers=T,
                  json={"user_id": third}, timeout=60)
    show("DELETE .../party/<someone else>  by a plain member",
         requests.delete(f"{base}/api/challenges/{cid}/party/{third}",
                         headers=D, timeout=60).status_code, 403)
    show("DELETE .../party/<owner>  by a plain member",
         requests.delete(f"{base}/api/challenges/{cid}/party/{owner}",
                         headers=D, timeout=60).status_code, 403)
    show("DELETE .../party/<owner>  by the OWNER themselves",
         requests.delete(f"{base}/api/challenges/{cid}/party/{owner}",
                         headers=O, timeout=60).status_code, 409)

    _p("\n3. dana leaves, and it is her own request:")
    left = requests.delete(f"{base}/api/challenges/{cid}/party/{dana}",
                           headers=D, timeout=60)
    show("DELETE .../party/<herself>", left.status_code, 200)
    if left.ok and dana in [p.get("id") for p in left.json().get("party") or []]:
        bad.append("she is still on the roster the server sent back")

    _p("\n4. what leaving actually revokes:")
    for path in ("dashboard", "tools", "journal"):
        show(f"GET  .../{path}",
             requests.get(f"{base}/api/challenges/{cid}/{path}",
                          headers=D, timeout=60).status_code, 403)
    mine = requests.get(f"{base}/api/challenges", headers=D, timeout=60)
    ids = [c.get("id") for c in (mine.json().get("challenges") or [])] if mine.ok else []
    _p(f"  {'ok  ' if cid not in ids else 'FAIL'}  {mine.status_code:<4} "
       f"GET  /api/challenges  -- the quest is gone from her picker")
    if cid in ids:
        bad.append("the quest is still in her list, so it comes back on next load")

    _p("\n5. the owner's side of it:")
    dash = requests.get(f"{base}/api/challenges/{cid}/dashboard", headers=O, timeout=60)
    show("GET  .../dashboard  (the owner is unaffected)", dash.status_code, 200)
    if dash.ok:
        summary = dash.json().get("summary") or {}
        roster = [p.get("id") for p in (summary.get("party") or [])]
        facts = summary.get("group_facts") or []
        _p(f"  roster now : {len(roster)} -> {roster}")
        _p(f"  group facts: {len(facts)} (leaving must not delete what she found out)")
        if dana in roster:
            bad.append("dana is still on the owner's roster after leaving")
        if not facts:
            bad.append("the party's shared memory is empty -- if it had facts before "
                       "this run, leaving destroyed them")

    # Tidy up after ourselves. A check that leaves two extra names on a live roster is
    # exactly the litter reap_test_users.py exists to sweep.
    requests.delete(f"{base}/api/challenges/{cid}/party/{third}", headers=O, timeout=60)

    if bad:
        _p("\n--- problems ---")
        for b in bad:
            _p("  * " + b)
        return 1
    _p("\nPASS: joining is reversible, and leaving takes the plan with it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
