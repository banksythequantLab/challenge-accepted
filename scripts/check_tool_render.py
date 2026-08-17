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
    python scripts\\check_tool_render.py chal_xxx --as ca_test_yyy --browser

Exit 1 if a tool the user is meant to OPERATE falls through to raw source. `script` and
`research_brief` are prose by design and do not count against it.

`--browser` goes further and opens each runnable page in real Chromium: does it throw,
does it render anything at all, and does it show the worked example the Toolwright was
told to put in a `data-smoke` element? That last one is the only thing standing between
"the arithmetic was proved in Python" and "the JavaScript the user actually runs does
the same arithmetic" -- a hand port that nothing checks is a hand port that drifts.
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
LOOKS_PYTHON = re.compile(r"^\s*(import |from |def |class |#!)", re.M)
HAS_MARKUP = re.compile(r"<[a-z][\s\S]*>", re.I)

#: The types the user is meant to OPERATE. app.html runs these in an iframe, wrapping
#: a bare fragment in a minimal document if that is all the model produced.
RUNNABLE = ("mini_app", "calculator", "tracker", "drill")

APP_HTML = Path(__file__).resolve().parent.parent / "challenge_accepted" / "static" / "app.html"

#: The tool page is loaded into a REAL sandboxed iframe with the same flags app.html
#: uses, not into a bare Playwright page.
#:
#: The first version of this used `page.set_content` plus `add_init_script` to fake the
#: sandbox, and `add_init_script` does not apply to `set_content` -- it only runs on
#: navigation -- so the shim never executed and a tool that works in the product was
#: reported as broken. Simulating an environment is how a check ends up measuring its
#: own simulation. Use the environment.
HOST_PAGE = ("<!doctype html><meta charset='utf-8'><body style='margin:0'>"
             "<iframe id='f' style='width:100%;height:600px;border:0' "
             "sandbox='allow-scripts allow-forms allow-modals'></iframe>")


def _shim_from_app_html() -> str:
    """app.html's own storage stub, read out of the file rather than copied.

    Two copies of this would be two things to keep in step, and the copy in the check
    is the one nobody would notice going stale -- it would quietly start measuring a
    shim the product no longer has. Read the real one; fail loudly if it moves.
    """
    text = APP_HTML.read_text(encoding="utf-8")
    m = re.search(r"const STORAGE_SHIM = `(<script>[\s\S]*?)<\\/script>`;", text)
    if not m:
        raise SystemExit(
            "could not find STORAGE_SHIM in app.html -- this check reproduces the "
            "product's own stub and will not guess at it")
    return m.group(1) + "</script>"


STORAGE_SHIM = _shim_from_app_html()


def with_shim(doc: str) -> str:
    """app.html's `withStorageShim`, in Python. Head first, so it beats page scripts."""
    head = re.search(r"<head[^>]*>", doc, re.I)
    if head:
        return doc.replace(head.group(0), head.group(0) + STORAGE_SHIM, 1)
    html = re.search(r"<html[^>]*>", doc, re.I)
    if html:
        return doc.replace(html.group(0), html.group(0) + "<head>" + STORAGE_SHIM + "</head>", 1)
    dt = re.search(r"<!doctype html>", doc, re.I)
    if dt:
        return doc.replace(dt.group(0), dt.group(0) + STORAGE_SHIM, 1)
    return STORAGE_SHIM + doc

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
    if LOOKS_HTML.search(src):
        return "runs", "sandboxed iframe"
    if (tool.get("type") in RUNNABLE and HAS_MARKUP.search(src)
            and not LOOKS_PYTHON.search(src)):
        return "runs", "iframe (fragment, wrapped)"
    if tool.get("type") in RUNNABLE:
        return "SOURCE", (f"type '{tool.get('type')}' should be an HTML page and this "
                          f"is {'Python' if LOOKS_PYTHON.search(src) else 'not markup'}")
    if tool.get("type") == "checklist":
        items = checklist_items(src)
        if items:
            return "runs", f"{len(items)} tick boxes"
        return "SOURCE", "typed checklist, but the JSON did not parse into items"
    # `script` and `research_brief` are prose the user READS. Rendering them as text is
    # the design, not a gap -- counting them as failures would make this check cry wolf
    # forever and nobody would read its output twice.
    if tool.get("type") in ("script", "research_brief"):
        return "reads", "prose, by design"
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
    browser = "--browser" in args
    if browser:
        args.remove("--browser")
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
    dead, runs, reads = [], [], []
    for t in tools:
        how, why = verdict(t)
        _p(f"  [{how:<6}] {(t.get('type') or '?'):<14} {(t.get('name') or '')[:44]:<44} {why}")
        (runs if how == "runs" else reads if how == "reads" else dead).append(t)

    _p(f"\n{len(runs)} run, {len(reads)} are prose by design, "
       f"{len(dead)} fall through to source code in a box")
    if dead:
        _p("\nA tool you have to read is a plan. What fell through:")
        for t in dead:
            _p(f"  * {t.get('type')} -- {t.get('name')}")
        return 1
    _p("\nPASS: every tool the user is meant to OPERATE actually opens and runs.")

    if browser:
        return live_check(tools)
    return 0


def live_check(tools: list[dict]) -> int:
    """Open each runnable tool in a real browser and read its `data-smoke` line.

    Static predicates only prove the dashboard will *try* to run the page. Whether the
    page WORKS is a different question, and it is the one that matters: the Toolwright
    proves its arithmetic in Python and then ports it to JavaScript by hand, and
    nothing about that port is checked. A page that throws on load renders as a blank
    white iframe, which from a screenshot looks like a tool with a minimal design.
    """
    from playwright.sync_api import sync_playwright

    runnable = [t for t in tools if verdict(t)[0] == "runs"
                and (t.get("type") or "") in RUNNABLE]
    if not runnable:
        _p("\nno runnable HTML tools to open -- nothing for the browser to check")
        return 0

    _p(f"\n--- opening {len(runnable)} tools in a real browser ---")
    bad = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for t in runnable:
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            src = t.get("source") or ""
            if not LOOKS_HTML.search(src):
                src = "<!doctype html><meta charset='utf-8'>" + src
            page.set_content(HOST_PAGE, wait_until="load")
            # srcdoc is set from JS rather than written into the attribute, so nothing
            # here has to get HTML-escaping of the tool's own markup right.
            page.evaluate("d => { document.getElementById('f').srcdoc = d; }",
                          with_shim(src))
            page.wait_for_timeout(600)
            frame = page.frame_locator("#f")
            smoke = frame.locator("[data-smoke]")
            shown = smoke.first.inner_text().strip() if smoke.count() else ""
            body = (frame.locator("body").inner_text() or "").strip()
            name = (t.get("name") or "")[:40]
            leans = "storage" if re.search(r"\b(local|session)Storage\b", src) else ""
            _p(f"  {name:<42} smoke={shown[:40]!r:<42} errors={len(errors)} {leans}")
            if leans:
                # Not a failure: the shim carries it and the tool works. But the page
                # believes it is saving the user's data and it is not, so say so
                # rather than letting a silent stub pass for persistence.
                _p("      ^ uses browser storage; the shim keeps it in memory, so "
                   "anything it 'saves' is gone when the modal closes")
            if errors:
                bad.append(f"{name}: threw on load -- {errors[0][:120]}")
            elif not body:
                bad.append(f"{name}: renders a blank page")
            elif not shown:
                bad.append(f"{name}: no [data-smoke] line, so the JS port is unverified")
        browser.close()

    if bad:
        _p("\n--- problems ---")
        for b in bad:
            _p("  * " + b)
        return 1
    _p("\nPASS: every page loads clean and shows its worked example.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
