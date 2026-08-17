"""Of the tools FORGE builds, how many can you actually USE in the dashboard?

The pitch is one sentence long: *every other AI gives you a plan, this one builds you
the tools*. The dashboard makes good on that for exactly two shapes --

  * `mini_app`, or anything whose source `looksHTML`, runs in a sandboxed iframe;
  * `checklist`, whose items become real tick boxes that remember what you ticked.

Everything else falls through to `<pre class="src">`, which is source code in a box. A
`calculator` you have to read rather than use is a plan with syntax highlighting, and
it is indistinguishable from a working product in a screenshot -- which is exactly the
class of gap this repo keeps finding the hard way.

So this counts it, on a real challenge, on the deployed service. It renders nothing: it
applies the same two predicates `app.html` applies (`looksHTML`, then `checklistItems`)
and reports what fraction of tools survive them.

    python scripts\\check_tool_render.py chal_xxx --as ca_test_yyy

Exit 1 if any tool falls through to raw source. That is a deliberately strict bar -- it
will fail today. The number it prints is the point, not the exit code.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_URL = "https://challengeaccepted.app"

#: Transcribed from app.html, not approximated:
#:     const looksHTML = s => /<html[\s>]|<!doctype html/i.test(s || '');
#: A check that guesses at the predicate it is measuring is measuring its own guess.
LOOKS_HTML = re.compile(r"<html[\s>]|<!doctype html", re.I)

#: app.html's `checklistItems`: parse JSON, take the first array under a known key
#: (falling back to the first array-valued key at all), and keep entries with text.
ITEM_KEYS = ("items", "steps", "checklist", "tasks", "list")
TEXT_KEYS = ("text", "item", "task", "label", "title", "step", "name", "description")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def checklist_items(src: str) -> list | None:
    try:
        data = json.loads(src)
    except (json.JSONDecodeError, TypeError):
        return None
    rows = _find_array(data)
    if not rows:
        return None
    out = []
    for it in rows:
        if isinstance(it, str) and it.strip():
            out.append(it)
        elif isinstance(it, dict):
            # Known key, or failing that any string field at all -- the model names
            # its own fields and `{day, workout}` is a real shape a live tool used.
            if any(it.get(k) for k in TEXT_KEYS) or any(
                    isinstance(v, str) and v.strip() for v in it.values()):
                out.append(it)
    return out or None


def _find_array(v):
    """Known keys, then any array here, then deeper. Depth LAST, like app.html."""
    if isinstance(v, list):
        return v
    if not isinstance(v, dict):
        return None
    for k in ITEM_KEYS:
        if isinstance(v.get(k), list):
            return v[k]
    for val in v.values():
        if isinstance(val, list):
            return val
    for val in v.values():
        if isinstance(val, dict):
            hit = _find_array(val)
            if hit:
                return hit
    return None


def verdict(tool: dict) -> tuple[str, str]:
    """(how it renders, why)."""
    src = tool.get("source") or ""
    if not src:
        return "empty", "no saved content -- the modal says so and stops"
    if tool.get("type") == "mini_app" or LOOKS_HTML.search(src):
        return "runs", "sandboxed iframe"
    if tool.get("type") == "checklist":
        items = checklist_items(src)
        if items:
            return "runs", f"{len(items)} tick boxes"
        return "SOURCE", "typed checklist, but the JSON did not parse into items"
    return "SOURCE", f"type '{tool.get('type')}' has no renderer"


def main() -> int:
    args = [a for a in sys.argv[1:]]

    def take(flag, default=None):
        if flag in args:
            i = args.index(flag)
            val = args[i + 1]
            del args[i:i + 2]
            return val
        return default

    uid = take("--as")
    base = (take("--url") or DEFAULT_URL).rstrip("/")
    if not args:
        _p("usage: check_tool_render.py <challenge_id> --as <uid>")
        return 2
    cid = args[0]

    health = requests.get(f"{base}/api/healthz", timeout=60).json()
    auth = {}
    if health.get("auth") == "required":
        if not uid:
            _p("this deployment needs --as <uid> of somebody on the challenge's party")
            return 2
        from testauth import mint

        auth = {"Authorization": "Bearer " + mint(uid)}

    r = requests.get(f"{base}/api/challenges/{cid}/tools", headers=auth, timeout=90)
    if not r.ok:
        _p(f"{r.status_code} reading tools -- the CHECK was refused, not the product")
        return 2
    payload = r.json()
    tools = payload.get("tools", payload) if isinstance(payload, dict) else payload

    if not tools:
        _p(f"{cid} has no tools")
        return 1

    _p(f"{len(tools)} tools on {cid}\n")
    dead = []
    for t in tools:
        how, why = verdict(t)
        _p(f"  [{how:<6}] {(t.get('type') or '?'):<14} {(t.get('name') or '')[:44]:<44} {why}")
        if how != "runs":
            dead.append(t)

    usable = len(tools) - len(dead)
    _p(f"\n{usable} of {len(tools)} tools are usable in the dashboard; "
       f"{len(dead)} render as source code in a box")
    if dead:
        _p("\nA tool you have to read is a plan. The types with no renderer:")
        for t in sorted({(t.get('type') or '?') for t in dead}):
            _p(f"  * {t}")
        return 1
    _p("\nPASS: every tool FORGE built can be used, not just read.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
