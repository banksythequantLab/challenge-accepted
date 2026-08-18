"""Does the group-fact budget actually bind, on the DEPLOYED service?

`tests/test_group_fact_budget.py` pins the ranking function. That is worth having and
it is not the same claim: the function could be perfect while `read_challenge_state`
never calls it, or calls it and then hands the model the unbounded list anyway. Unit
tests have been wrong about this product in exactly that way before -- 161 of them
passed while the deployed service built no tools at all.

So this drives the real thing:

  1. seed a party's shared memory past the budget with obvious filler;
  2. run ONE turn against production;
  3. assert the tool result the model received was TRIMMED, and that it carried the
     marker saying so -- a silently trimmed list is a lie by omission;
  4. take the filler back out, whatever happened.

    python scripts\\check_fact_budget_live.py <challenge_id> --as <uid>

Costs one cheap turn. The filler is removed in a `finally`, so a crash mid-run does not
leave sixty junk facts on a live party.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_URL = "https://challengeaccepted.app"
APP = "challenge_accepted"
MARK = "ca-filler-"

#: Vocabulary for the filler. Single words on purpose, and the sentences around them
#: are as thin as possible.
#:
#: `add_group_fact` dedups on content-word overlap measured against the SMALLER set,
#: so any boilerplate shared by every filler sentence counts against every pair. The
#: first version wrote "the {noun} {verb} whenever the {place} is involved, noted on
#: visit {i}" and Firestore stored 3 of 56 -- the shared scaffolding alone cleared the
#: threshold. The store was right; the check was writing 56 rephrasings of one fact.
NOUNS = ["archivist", "locksmith", "tangerine", "harbourmaster", "kiln", "ferry",
         "beekeeper", "violin", "quarry", "lighthouse", "cartwright", "orchard",
         "tannery", "seamstress", "millpond", "bellfoundry", "saltmarsh", "cooper",
         "windmill", "fishmonger"]
VERBS = ["closes", "dawdles", "overbooks", "deposits", "refuses", "reopens",
         "misfiles", "surcharges", "relocates", "hushes"]
PLACES = ["northbridge", "customshouse", "eastpier", "marketsquare", "granarylane",
          "riversideyard", "cathedralclose", "stonewharf", "hollowlane", "chandlersrow"]


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main() -> int:
    args = list(sys.argv[1:])
    base = args.pop(0).rstrip("/") if args and args[0].startswith("http") else DEFAULT_URL
    uid = args[args.index("--as") + 1] if "--as" in args else None
    args = [a for a in args if not a.startswith("--") and a != uid]
    if not args or not uid:
        _p("usage: check_fact_budget_live.py [url] <challenge_id> --as <uid>")
        return 2
    cid = args[0]

    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0955694243")
    from challenge_accepted import config
    from challenge_accepted.services.store import store
    from challenge_accepted.services.tools import GROUP_FACT_BUDGET
    from testauth import mint

    if not config.use_firestore():
        _p("REFUSING: seeding would go into an in-memory stub this process owns, not "
           "the store the deployed service reads. Set GOOGLE_CLOUD_PROJECT.")
        return 2

    challenge = store.get("challenges", cid) or {}
    gid = str(challenge.get("group_id") or "")
    if not gid:
        _p(f"{cid} has no group")
        return 1

    before = list((store.get("groups", gid) or {}).get("shared_facts") or [])
    need = GROUP_FACT_BUDGET + 20 - len(before)
    _p(f"group {gid}: {len(before)} facts, budget {GROUP_FACT_BUDGET}, "
       f"seeding {max(0, need)} filler\n")

    auth = {"Authorization": "Bearer " + mint(uid)}
    bad: list[str] = []
    try:
        # Each filler fact must be about DIFFERENT things, not the same sentence with a
        # counter on it. `add_group_fact` dedups on normalised content-word overlap --
        # correctly, that is how three phrasings of one constraint got collapsed -- so
        # the first attempt at this seeded 56 facts and stored exactly 1, then reported
        # the budget as broken. The check was wrong, the store was right.
        for i in range(max(0, need)):
            # Every content word is suffixed with the index, so no two filler facts
            # share ANY token but the word "filler". Recombining a fixed vocabulary was
            # not enough -- with 20 nouns and 10 places the pairs repeat, three of five
            # tokens match and the dedup (correctly) called them the same fact. It
            # stored 20 of 56 and the check blamed the budget. Make them genuinely
            # distinct rather than arguing with a deduplicator that is doing its job.
            a = NOUNS[i % len(NOUNS)]
            b = VERBS[(i // len(NOUNS)) % len(VERBS)]
            c = PLACES[i % len(PLACES)]
            store.add_group_fact(gid, f"{MARK}{i:03d}: {a}{i:02d} {b}{i:02d} {c}{i:02d}.")
        seeded_order = list((store.get("groups", gid) or {}).get("shared_facts") or [])
        _p(f"group now holds {len(seeded_order)} facts")

        sid = "s_" + uuid.uuid4().hex[:10]
        requests.post(f"{base}/apps/{APP}/users/{uid}/sessions", headers=auth, timeout=90,
                      json={"session_id": sid,
                            "state": {"user_id": uid, "challenge_id": cid}})
        r = requests.post(f"{base}/run_sse", headers=auth, timeout=600, json={
            "app_name": APP, "user_id": uid, "session_id": sid, "streaming": False,
            "new_message": {"role": "user", "parts": [{"text":
                "Remind me what the team already knows about this quest."}]}})
        raw = r.text

        # What the MODEL received, not what the store holds. That is the whole point:
        # the budget is only real if it binds on the way into the prompt.
        got = [json.loads(line[5:]) for line in raw.splitlines() if line.startswith("data:")]
        responses = [p["functionResponse"]["response"]
                     for ev in got for p in (ev.get("content") or {}).get("parts") or []
                     if p.get("functionResponse")
                     and p["functionResponse"].get("name") == "read_challenge_state"]
        if not responses:
            _p("no read_challenge_state in the stream -- nothing to measure. This is "
               "the check failing to observe, not the budget failing to bind.")
            return 2

        for i, resp in enumerate(responses):
            facts = resp.get("group_facts") or []
            withheld = resp.get("group_facts_withheld")
            note = resp.get("group_facts_note") or ""
            fillers = len([f for f in facts if MARK in str(f)])
            _p(f"\nread_challenge_state #{i + 1}:")
            _p(f"  facts in the prompt : {len(facts)}  (budget {GROUP_FACT_BUDGET})")
            _p(f"  of those, filler    : {fillers}")
            _p(f"  withheld            : {withheld}")
            _p(f"  note                : {note[:96]}")
            if len(facts) > GROUP_FACT_BUDGET:
                bad.append(f"call #{i + 1} sent {len(facts)} facts, over the budget of "
                           f"{GROUP_FACT_BUDGET} -- the trim is not on this path")
            if not withheld:
                bad.append(f"call #{i + 1} trimmed silently: no `group_facts_withheld`, "
                           "so the model believes it was told everything")
            # Asserted again, and the history of this one assertion is the whole story
            # of the feature.
            #
            # v1 failed the run when any real fact was evicted. That was asserting a
            # guarantee the LEXICAL design could not make: a fact sharing no words with
            # the charter was indistinguishable from filler sharing none, and recency
            # broke the tie in filler's favour. It measured 3 of 4 and the assertion
            # had to be downgraded to a report, because a check that only passes when
            # the ranking gets lucky is worse than no check.
            #
            # v2 added embeddings and got WORSE -- 2 of 4 -- because it mixed cosine
            # scores with a rescaled word-overlap in one sort, and unrelated text
            # embeds at ~0.66, not ~0. The report is what caught that; an assertion
            # would only have said "still not guaranteed".
            #
            # v3 ranks on one scale and backfills the vectors, and this is a real bar
            # again: with every fact embedded, the party's own discoveries outranking
            # machine-generated gibberish is something the design DOES promise.
            real_kept = [f for f in facts if MARK not in str(f)]
            _p(f"  real facts survived : {len(real_kept)} of {len(before)}")
            if before and len(real_kept) < len(before) and fillers:
                bad.append(
                    f"call #{i + 1} kept {fillers} pieces of filler while dropping "
                    f"{len(before) - len(real_kept)} of the party's real discoveries. "
                    "Every fact here is embedded, so this is the ranking being wrong "
                    "rather than the ranking being unable to tell")
            newest = [f for f in seeded_order[-3:] if f not in facts]
            if newest:
                bad.append(f"call #{i + 1} dropped {len(newest)} of the three NEWEST "
                           "facts -- recency is supposed to be unconditional")
    finally:
        # Trim BOTH lists, index by index. The first version dropped the filler from
        # `shared_facts` and left `fact_vectors` at 60, so the group carried 60 vectors
        # against 4 facts -- an alignment the ranker depends on, broken by the cleanup
        # of the check that measures the ranker. Rebuild the pair together.
        doc = store.get("groups", gid) or {}
        old_facts = list(doc.get("shared_facts") or [])
        old_vecs = list(doc.get("fact_vectors") or [])
        pairs = [(f, old_vecs[i] if i < len(old_vecs) else {})
                 for i, f in enumerate(old_facts) if MARK not in str(f)]
        doc["shared_facts"] = [f for f, _ in pairs]
        doc["fact_vectors"] = [v for _, v in pairs]
        store._put("groups", gid, doc)
        _p(f"\ncleaned up: group back to {len(pairs)} facts "
           f"({len([1 for _, v in pairs if (v or {}).get('v')])} vectored)")

    if bad:
        _p("\n--- problems ---")
        for b in bad:
            _p("  * " + b)
        return 1
    _p("\nPASS: the budget binds on the deployed service, and it says what it dropped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
