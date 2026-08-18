"""Give a vector to every group fact written before embeddings existed.

The ranker survives a mixed store -- unembedded facts sit at the median cosine, neither
punished nor favoured -- but "survives" is not "is correct". A fact scored at the median
by definition cannot rise above half the party's memory no matter how relevant it is,
so a party whose history predates this change would have that history permanently
capped at mediocre.

This makes the mixed case stop existing. Run once after deploying embeddings; safe to
re-run, because it only embeds facts that have no vector.

    python scripts\\backfill_fact_vectors.py               # show what is missing
    python scripts\\backfill_fact_vectors.py --commit      # embed and save

One embedding call per BATCH of facts per group, not per fact -- `embed()` takes a list
and the whole point of doing this offline is that it does not have to be cheap per item,
only bounded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BATCH = 32


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main() -> int:
    commit = "--commit" in sys.argv
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0955694243")

    from challenge_accepted import config
    from challenge_accepted.services import embeddings
    from challenge_accepted.services.store import store

    if not config.use_firestore():
        _p("REFUSING: this is the in-memory store, so a clean sweep here would mean "
           "nothing. Set GOOGLE_CLOUD_PROJECT and have ADC.")
        return 2
    if not embeddings.available():
        _p("REFUSING: embeddings are unavailable, so there is nothing to backfill "
           "WITH. Fix that first -- silently writing no vectors and reporting success "
           "is the failure this whole file is here to undo.")
        return 2

    _p(f"store: firestore  project: {config.GOOGLE_CLOUD_PROJECT}")
    _p(f"model: {embeddings.MODEL}  dim: {embeddings.DIM}\n")

    groups = {}
    for challenge in store.list_challenges(None):
        gid = str(challenge.get("group_id") or "")
        if gid:
            groups[gid] = None

    total_missing, total_done, failed = 0, 0, []
    for gid in sorted(groups):
        doc = store.get("groups", gid) or {}
        facts = list(doc.get("shared_facts") or [])
        if not facts:
            continue
        vectors = list(doc.get("fact_vectors") or [])
        if len(vectors) > len(facts):
            # Repaired, and said out loud. A vector list LONGER than the fact list means
            # something deleted facts without deleting their vectors, and this is the
            # only place that would ever notice.
            _p(f"{gid}: REPAIRING alignment -- {len(vectors)} vectors for "
               f"{len(facts)} facts")
            vectors = vectors[:len(facts)]
        while len(vectors) < len(facts):
            vectors.append({})

        missing = [i for i, row in enumerate(vectors) if not (row or {}).get("v")]
        if not missing:
            if commit and vectors != list(doc.get("fact_vectors") or []):
                doc["fact_vectors"] = vectors        # alignment repair with nothing to embed
                store._put("groups", gid, doc)
                _p(f"  -> alignment fixed, {len(vectors)} vectors for {len(facts)} facts")
            continue
        total_missing += len(missing)
        _p(f"{gid}: {len(missing)} of {len(facts)} facts have no vector")
        if not commit:
            continue

        got_any = False
        for start in range(0, len(missing), BATCH):
            chunk = missing[start:start + BATCH]
            vecs = embeddings.embed([facts[i] for i in chunk], task="RETRIEVAL_DOCUMENT")
            if not vecs:
                failed.append(f"{gid}: batch at {start} returned nothing")
                continue
            for i, vec in zip(chunk, vecs):
                vectors[i] = {"v": vec}
            got_any = True

        # Written once per group rather than per batch. A partial group is fine to
        # re-run over; a group written 20 times is 20 chances to lose a concurrent
        # `add_group_fact` that landed between reads.
        if got_any:
            doc["shared_facts"] = facts
            doc["fact_vectors"] = vectors
            store._put("groups", gid, doc)
            done = len([1 for row in vectors if (row or {}).get("v")])
            total_done += done
            _p(f"  -> saved, {done} of {len(facts)} now vectored")

    if not total_missing:
        _p("nothing to backfill -- every group fact already has a vector")
    elif not commit:
        _p(f"\n{total_missing} facts have no vector. Re-run with --commit.")
    else:
        _p(f"\nbackfilled across {len(groups)} group(s)")

    if failed:
        _p("\n--- problems ---")
        for f in failed:
            _p("  * " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
