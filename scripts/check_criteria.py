"""Can the user actually satisfy the criteria the Cartographer wrote?

The Referee reads an acceptance criterion literally and refuses anything short of it --
which is correct, and which is exactly why the criterion has to be reachable. The user
has one chat box. They can state a number, a date, a name or a link. They cannot hand
over a file.

A real graph, measured before this was fixed:

    5 of 11 criteria demanded an artifact the UI has no way to accept
      "GPS activity log file of 5k time trial saved..."
      "Receipt and photo/log of fitted running shoes ... saved."
      "Official race registration confirmation email/ticket ... saved as a file."

Those steps could never be closed. Not a rendering bug and not a model failure --
the Cartographer's own prompt used "Draft written and saved as a file" as its example
of a GOOD criterion, so the plan was being written against a capability the product
does not have. The two halves of the app disagreed and nothing anywhere said so.

    python scripts\\check_criteria.py chal_xxx --as ca_test_yyy
    python scripts\\check_criteria.py --file some_graph.json

Exit 1 if any live criterion demands an artifact.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_URL = "https://challengeaccepted.app"

#: Words that name a thing the user would have to HAND OVER. A link is deliberately not
#: on this list -- people can paste a URL, and asking for one is good practice.
ARTIFACT = re.compile(
    r"\b(photo|photograph|screenshot|receipt|invoice|upload(?:ed)?|attach(?:ed|ment)?|"
    r"image|scan(?:ned)?|\.pdf|pdf|spreadsheet|csv|log file|file saved|saved as a file|"
    r"document saved|saved to (?:a |your )?(?:file|folder|drive))\b", re.I)

#: "saved" on its own is ambiguous -- "plan saved" can mean "written down somewhere".
#: Only flag it when it is a saved THING, which is what the pattern above requires.


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def offenders(criteria: str) -> list[str]:
    return sorted({m.group(0).lower() for m in ARTIFACT.finditer(criteria or "")})


def report(rows: list[tuple[str, str, str]]) -> int:
    """rows of (node_id, status, criteria)."""
    bad = []
    for node_id, status, crit in rows:
        hits = offenders(crit)
        mark = "  <-- " + ", ".join(hits) if hits else ""
        _p(f"[{status:<4}] {node_id[:32]:<32} {(crit or '(none)')[:88]}{mark}")
        if hits:
            bad.append((node_id, hits))
        if not (crit or "").strip():
            bad.append((node_id, ["no criterion at all"]))

    _p(f"\n{len(bad)} of {len(rows)} criteria cannot be satisfied from a chat box")
    if bad:
        _p("\n--- problems ---")
        for node_id, hits in bad:
            _p(f" * {node_id}: asks for {', '.join(hits)} -- the Referee will refuse "
               f"this step forever")
        return 1
    _p("\nPASS -- every step can be closed by something the user can type.")
    return 0


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
    path = take("--file")
    base = (take("--url") or DEFAULT_URL).rstrip("/")

    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        nodes = data.get("nodes", data if isinstance(data, list) else [])
        return report([(n.get("id", "?"), n.get("status", "todo"),
                        n.get("acceptance_criteria", "")) for n in nodes])

    if not args:
        _p("usage: check_criteria.py <challenge_id> --as <uid>")
        return 2

    import requests

    from testauth import mint

    cid = args[0]
    headers = {}
    if requests.get(f"{base}/api/healthz", timeout=60).json().get("auth") == "required":
        if not uid:
            _p("this deployment needs --as <uid> of somebody on the party")
            return 2
        headers = {"Authorization": "Bearer " + mint(uid)}

    d = requests.get(f"{base}/api/challenges/{cid}/dashboard",
                     headers=headers, timeout=120).json()
    rows = [(n["id"], n["data"].get("status", "?"),
             n["data"].get("acceptance_criteria", ""))
            for n in (d.get("graph") or {}).get("nodes", [])]
    if not rows:
        _p(f"{cid} has no nodes")
        return 1
    return report(rows)


if __name__ == "__main__":
    sys.exit(main())
