"""Take the throwaway check identities back off the live party rosters.

Every live check signs in as `ca_test_<something>` (see testauth.py), and every one of
them that joins a challenge stays on its roster forever. That is not cosmetic. The
Party pane is the screen the Collaborative Partner claim rests on, and by the time
anyone looks at it, it reads:

    6 on this quest -- you and Forge Dc53A6, Dana B71C22, Derek Eb43D9, ...

which makes a real two-person party look like a load test. The identities are also the
reason the prefix exists: a check that leaves data behind should leave data that says
so, and this is the other half of that bargain.

    python scripts\\reap_test_users.py                 # show what would go
    python scripts\\reap_test_users.py --commit        # actually remove them

Runs against Firestore directly rather than through the API, because the API only lets
you remove yourself or somebody from a party you own, and this is a janitor rather than
a user. It never touches a challenge OWNER -- if a test identity started the quest, the
quest is the test artifact and deleting half of it would leave a challenge whose owner
is not on its own roster.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from challenge_accepted import config  # noqa: E402
from challenge_accepted.services.store import store  # noqa: E402

PREFIX = "ca_test_"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main() -> int:
    commit = "--commit" in sys.argv
    # Firestore is chosen by GOOGLE_CLOUD_PROJECT being set, not by a store flag. Get
    # that wrong and this runs happily against an empty in-memory stub, prints
    # "nothing to reap", and tells you the rosters are clean when it never looked at
    # them. Say which store this is before saying anything about what is in it.
    if not config.use_firestore():
        _p("REFUSING: this process is on the in-memory store, not Firestore. Set "
           "GOOGLE_CLOUD_PROJECT (and have ADC) or this reports a clean sweep of "
           "nothing at all.")
        return 2
    _p(f"store: firestore  project: {config.GOOGLE_CLOUD_PROJECT}")
    challenges = store.list_challenges(None)
    _p(f"{len(challenges)} challenges in the store\n")

    owned_by_tests, removals, kept = 0, [], 0
    for c in challenges:
        gid = str(c.get("group_id") or "")
        owner = str(c.get("owner_id") or "")
        if not gid:
            continue
        members = [str(m) for m in ((store.get("groups", gid) or {}).get("members") or [])]
        tests = [m for m in members if m.startswith(PREFIX)]
        if not tests:
            continue
        if owner.startswith(PREFIX):
            # The whole challenge is a test artifact. Stripping its roster would leave
            # an ownerless-looking quest, which is a worse mess than the one we came to
            # clean. Report it and leave it alone.
            owned_by_tests += 1
            continue
        title = ((c.get("charter") or {}).get("title") or c.get("id") or "")[:44]
        for m in tests:
            removals.append((c.get("id"), gid, m, title))
        kept += len([m for m in members if not m.startswith(PREFIX)])

    if not removals:
        _p("nothing to reap -- no test identity is sitting on a real person's quest")
    for cid, _gid, uid, title in removals:
        _p(f"  {'remove' if commit else '  would'}  {uid:<26} from {title} ({cid})")

    if commit:
        for _cid, gid, uid, _title in removals:
            store.leave_group(gid, uid)
        _p(f"\nremoved {len(removals)}; {kept} real members untouched")
    elif removals:
        _p(f"\n{len(removals)} to remove. Re-run with --commit.")

    if owned_by_tests:
        _p(f"\n{owned_by_tests} challenge(s) are OWNED by a test identity and were left "
           f"alone -- those are whole test artifacts, not litter on a real quest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
