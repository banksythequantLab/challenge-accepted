"""The party notebook must not be empty at the moment a teammate opens the invite.

A full production run -- 10 nodes, 6 tools, four Toolwrights -- left the Party pane
saying "Nothing learned yet. Discoveries land here for the whole party." while the
charter it had just written held the deadline, the constraints and everything already
tried. `remember_group_fact` only fires on a returning turn, so a fresh challenge had
nothing shared. The densest facts in the run were in the one place the pane never read.

save_charter now seeds the notebook from the charter. This checks that end to end
against the real store, with no model calls:

    python scripts\\check_party_facts.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from challenge_accepted.services import tools as T  # noqa: E402
from challenge_accepted.services.store import store  # noqa: E402


class FakeContext:
    """Enough ToolContext for save_charter: it only ever touches .state."""

    def __init__(self, user_id: str):
        self.state: dict = {"user_id": user_id, "group_id": f"grp_{user_id}"}


#: The charter save_charter actually wrote in production today, verbatim from the
#: session state of chal_e171b48edd34 -- including the "None (running solo)" that a
#: naive implementation would have published as a shared discovery.
REAL_CHARTER = dict(
    title="Run a 10k under 55 minutes by Christmas",
    outcome="Finish the official organized park 10k race on Christmas Eve (Dec 24) "
            "in under 55 minutes.",
    definition_of_done="Crossing the line at the Christmas Eve park 10k in under 55:00.",
    deadline="December 24",
    constraints=[
        "Available 4 evenings per week for ~45 minutes per session",
        "Starting baseline: runs ~3k twice a week at a slow pace, no prior "
        "structured training",
    ],
    prior_attempts=["Running 3k twice a week at slow pace without structured training"],
    stakeholders=["None (running solo)"],
)

fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        fails.append(msg)


async def main() -> int:
    ctx = FakeContext("u_facts_probe")
    res = await T.save_charter(tool_context=ctx, **REAL_CHARTER)
    check(res.get("status") == "ok", f"save_charter failed: {res}")

    gid = ctx.state["group_id"]
    facts = (store.get("groups", gid) or {}).get("shared_facts", [])
    print(f"party notebook after the interview ({len(facts)}):")
    for f in facts:
        print("  - " + f)

    check(bool(facts), "the party notebook is STILL empty after a charter is saved")
    joined = " || ".join(facts).lower()

    check("december 24" in joined, "the deadline was not shared with the party")
    check("4 evenings" in joined, "the user's time constraint was not shared")

    # Prior attempts are OFFERED to the notebook; whether they land is up to the
    # store's near-duplicate check. In this real charter the prior attempt restates
    # the baseline constraint almost word for word, and it is correctly collapsed --
    # asserting it survives would be asserting the dedup is broken.
    offered = T._charter_facts(REAL_CHARTER)
    check(any(f.startswith("Already tried:") for f in offered),
          "what the user already tried was never offered to the party notebook")
    if len(offered) > len(facts):
        print(f"\n(near-duplicate check collapsed {len(offered) - len(facts)} of "
              f"{len(offered)} candidate facts -- correct: the prior attempt restates "
              f"the baseline constraint)")

    check("running solo" not in joined,
          "'None (running solo)' was published as a shared discovery -- the notebook "
          "is echoing empty form fields back at the party")
    check(not any(REAL_CHARTER["title"].lower() == f.lower() for f in facts),
          "the title was duplicated into the notebook; it is already the headline")

    # The phrasings production actually produced for "there is nobody else". A real
    # named stakeholder must still get through -- this filter is for empty answers,
    # not for people.
    for nobody in ("None (running solo)", "Solo runner (no coach or training partners)",
                   "Just me", "N/A", "no team involved"):
        check(not any(f.startswith(f"Also involved: {nobody}")
                      for f in T._charter_facts({"stakeholders": [nobody]})),
              f"{nobody!r} would be published to the party as a discovery")
    check(any(f == "Also involved: My physio, Dr Chen"
              for f in T._charter_facts({"stakeholders": ["My physio, Dr Chen"]})),
          "a real named stakeholder was filtered out of the party notebook")

    # Saving the same charter again must not double the notebook: two people
    # re-running an interview should not produce a wall of near-duplicates.
    before = len(facts)
    ctx2 = FakeContext("u_facts_probe")
    ctx2.state["group_id"] = gid
    await T.save_charter(tool_context=ctx2, **REAL_CHARTER)
    after = len((store.get("groups", gid) or {}).get("shared_facts", []))
    check(after == before,
          f"re-saving the charter grew the notebook from {before} to {after}")

    if fails:
        print("\n--- problems ---")
        for f in fails:
            print(" * " + f)
        return 1
    print("\nPASS -- a teammate opening the invite link finds what the interview learned.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
