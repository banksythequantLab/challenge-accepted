"""What the dashboard costs Firestore while it just sits there.

The UI polls the read API every 4 seconds when idle and every 1.2 seconds during a run
-- deliberately, so the map grows on screen while the agents work. That makes the read
path a standing cost rather than an occasional one, and it is paid per open browser,
for the whole seven-week judging window.

`/api/challenges` populates the quest picker. It was doing one Firestore query PER
CHALLENGE to compute a node count nothing rendered, on top of the collection scan. So
the cost of a judge idling on the page grew linearly with the number of challenges
every previous judge had created.

This measures round trips rather than guessing at them: every Store read is counted,
the dashboard is left alone to poll, and the result is expressed as reads per minute
per open browser -- which is the number that actually shows up on a bill.

    python scripts\\check_poll_cost.py
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from challenge_accepted.api import router  # noqa: E402
from challenge_accepted.services.store import Store, store  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8147
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

#: A plausible end-of-judging state. Every judge who types a goal leaves one behind.
OTHER_CHALLENGES = 24

#: Seconds to sit on the page doing nothing. Long enough for several idle polls.
WATCH = 12.0

#: Reads per minute, per idle browser. A ceiling, not a target -- the point is to fail
#: loudly if the read path goes quadratic again, not to police small changes.
BUDGET = 120

reads: Counter = Counter()


def _instrument() -> None:
    """Count Store reads the way Firestore bills them: one per query, one per get."""
    real_query, real_get = Store._query, Store.get

    def counted_query(self, collection, field, value):
        reads[f"query:{collection}"] += 1
        return real_query(self, collection, field, value)

    def counted_get(self, collection, doc_id):
        reads[f"get:{collection}"] += 1
        return real_get(self, collection, doc_id)

    Store._query, Store.get = counted_query, counted_get

    real_list = Store.list_challenges

    def counted_list(self, group_id=None):
        reads["scan:challenges"] += 1
        return real_list(self, group_id)

    Store.list_challenges = counted_list


app = FastAPI()
app.include_router(router)


@app.get("/app")
def dashboard() -> FileResponse:
    return FileResponse(STATIC)


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def main() -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    _instrument()
    cid = seed()
    # Everyone else's quests. They are never opened; they only have to exist.
    for i in range(OTHER_CHALLENGES):
        other = store.create_challenge(
            {"title": f"Someone else's goal {i}"}, owner_id=f"u_{i}", group_id=f"g_{i}")
        for n in range(8):
            store.put_node(other, {"id": f"n{n}", "title": f"N{n}",
                                   "acceptance_criteria": "c"})
    total_challenges = len(store.list_challenges())
    _p(f"challenges in store : {total_challenges}")

    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 940})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1500)

        reads.clear()          # ignore first paint; measure the STANDING cost
        start = time.time()
        page.wait_for_timeout(int(WATCH * 1000))
        elapsed = time.time() - start

        polls = page.evaluate("() => performance.getEntriesByType('resource')"
                              ".filter(r => r.name.endsWith('/dashboard')).length")
        browser.close()

    total = sum(reads.values())
    per_min = total / elapsed * 60

    _p(f"\nwatched            : {elapsed:.1f}s, {polls} graph fetches")
    _p(f"store reads        : {total}")
    for k, v in sorted(reads.items(), key=lambda kv: -kv[1]):
        _p(f"  {k:<24} {v}")
    _p(f"\nreads / minute     : {per_min:.0f}  (budget {BUDGET})")
    _p(f"page errors        : {errors if errors else 'none'}")

    node_queries = reads.get("query:nodes", 0)
    _p(f"node queries       : {node_queries}")

    if errors:
        sys.exit(f"FAIL: page errors {errors}")
    if per_min > BUDGET:
        sys.exit(
            f"FAIL: {per_min:.0f} Firestore reads/minute for ONE idle browser, budget "
            f"{BUDGET}. With {total_challenges} challenges in the store that is "
            f"{node_queries} node queries in {elapsed:.0f}s -- the picker is doing a "
            "query per challenge it will never show."
        )

    _p("\nthe idle dashboard is cheap. ")


if __name__ == "__main__":
    main()
