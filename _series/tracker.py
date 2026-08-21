"""Pull the real state of the $25k challenge, for the series to open on.

Every episode should start from what is actually true, not from a claim about it.
This reads chal_1a7cbac10402 out of Firestore -- the same challenge the demo video
shows -- and writes a small JSON the tracker page renders from.

Read-only. get() and list_*() only. Nothing here writes to the database.

The honest part: as of writing, ALL FIFTEEN NODES ARE status=todo. Ten of them have
a tool with smoke_test_passed=True, which is a real thing that happened, and it is
not the same thing as a task being done. The page shows those as two separate
numbers and never adds them together.

    python _series\\tracker.py    ->  _series\\progress.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHALLENGE = "chal_1a7cbac10402"
GOAL = "$25,000 / month in 90 days, from directory and rank-and-rent sites"
START = "$0 earned  |  $1,500 budget  |  34 domains"

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0955694243")
sys.path.insert(0, str(HERE.parent))

from challenge_accepted.services.store import Store   # noqa: E402

DONE = {"done", "complete", "completed", "cleared"}


def main() -> int:
    store = Store()
    if store.backend != "firestore":
        raise SystemExit(f"store backend is {store.backend!r}, not firestore -- "
                         f"this would render a made-up page")

    nodes = store.list_nodes(CHALLENGE)
    tools = store.list_tools(CHALLENGE)
    by_node: dict[str, list[dict]] = {}
    for t in tools:
        if t.get("smoke_test_passed"):
            by_node.setdefault(t.get("node_id"), []).append(
                {"name": t.get("name"), "type": t.get("tool_type"),
                 "usage": (t.get("usage") or "")[:400]})

    rows = []
    for n in nodes:
        status = (n.get("status") or "todo").lower()
        rows.append({
            "id": n.get("id"),
            "title": n.get("title") or n.get("name") or "",
            "status": status,
            "done": status in DONE,
            "depends_on": n.get("depends_on") or [],
            "acceptance": (n.get("acceptance")
                           or n.get("acceptance_criterion") or "")[:400],
            "tools": by_node.get(n.get("id"), []),
        })

    out = {
        "challenge": CHALLENGE,
        "goal": GOAL,
        "start": START,
        "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {
            "nodes": len(rows),
            "done": sum(1 for r in rows if r["done"]),
            "with_tool": sum(1 for r in rows if r["tools"]),
            "tools": sum(len(r["tools"]) for r in rows),
        },
        "nodes": rows,
    }
    (HERE / "progress.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    c = out["counts"]
    print(f"{HERE / 'progress.json'}")
    print(f"  {c['nodes']} nodes   {c['done']} done   "
          f"{c['with_tool']} with a smoke-tested tool   {c['tools']} tools")
    if c["done"] == 0:
        print("  nothing is done yet -- that is the honest starting line")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
