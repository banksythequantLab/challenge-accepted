"""Does a tool remember, in a real browser, on the deployed site?

`tests/test_tool_state.py` proves the endpoint. That is not the claim. The claim is
that a person can open a tracker, log something, close the tab, come back tomorrow and
still have it -- and between the endpoint and that sentence sit four things no unit
test touches: a sandboxed iframe with no storage, a shim that replaces `localStorage`,
a `postMessage` hop to the parent, and a debounced save that has to survive the modal
being closed 200ms later.

Every one of those is a place where the tool appears to save and does not. That is the
worst failure this feature has, because it is silent and the user only discovers it
much later, when the log they have been keeping turns out to be empty.

So this drives the whole path:

  1. open a real tool on the deployed dashboard, in a signed-in browser;
  2. write into it the way a tool does -- `localStorage.setItem` from inside the frame;
  3. close the modal immediately, inside the debounce window;
  4. RELOAD THE WHOLE PAGE, so nothing in memory can be carrying the answer;
  5. reopen the tool and read the value back out of the iframe.

    python scripts\\check_tool_memory.py <challenge_id> --as <uid>

Exit 0 only if the value survives the reload. Costs no model calls.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_party_ui import DEFAULT_URL, _p, open_as  # noqa: E402


RUNNABLE = ("mini_app", "calculator", "tracker", "drill")


def in_frame(page, js: str):
    """Run JS inside the tool's sandboxed iframe."""
    return page.frame_locator("#frame").locator("body").evaluate(js)


def _clear(base: str, cid: str, tool_id: str, auth: dict, bad: list) -> None:
    """Put the tool's state back to empty, and never let teardown fail the run.

    This check writes a marker into a REAL tool on a REAL challenge, so it has to
    clean up after itself -- leaving `logged-f07170ed` in somebody's prospect tracker
    is rude. But cleanup is not the thing being measured, and a dropped TLS connection
    on the way out should not turn a run where every assertion passed into a traceback
    with no verdict at the bottom. That happened: persistence proved, checklist tick
    proved, four tools opened clean, and then `ConnectionResetError` on the final PUT
    swallowed the whole result.

    So it retries once, and if it still cannot clear, it says so as a *finding* rather
    than an exception -- because leftover state in a user's tool is worth knowing about
    even when nothing about the product is broken.
    """
    for attempt in (1, 2):
        try:
            requests.put(f"{base}/api/challenges/{cid}/tools/{tool_id}/state",
                         headers=auth, json={"state": {}}, timeout=60)
            _p(f"cleaned up: {tool_id} state cleared")
            return
        except requests.RequestException as exc:                    # noqa: PERF203
            if attempt == 2:
                why = type(exc).__name__
                bad.append(f"could not clear test state from {tool_id} ({why}); "
                           "it may still be sitting in the user's tool")
            else:
                time.sleep(2)


def open_tool(page, tool_id: str, timeout: int = 20000) -> None:
    # Calling the product's own opener rather than clicking a node, then a tool card.
    # That path is real but it is navigation, and a failure in it would be reported
    # here as "the tool does not remember" -- which would be a lie about this feature.
    #
    # WAIT FOR THE TOOL TO EXIST FIRST. `openTool` reads `toolsById`, which `refresh()`
    # fills, and calling it before the dashboard has landed is a silent no-op: no
    # iframe, no error, and 20s later a timeout that reads as "the tool would not
    # open". That is what happened on a cold Cloud Run instance the first time this
    # check was pointed at a freshly built challenge -- against eight tools that
    # `check_tool_render.py --browser` had opened cleanly minutes earlier.
    #
    # `open_as` waits a fixed 3 seconds after sign-in, and a fixed wait that is
    # slightly too short does not fail, it lies. Same fix as `wait_for_dashboard` in
    # check_party_ui.py and the `toolsById` guard in check_shared_tool_ui.py -- this
    # file is the third place to need it, which is three times the lesson has cost
    # something.
    page.wait_for_function(
        "id => typeof toolsById !== 'undefined' && !!toolsById[id]",
        arg=tool_id, timeout=timeout)
    page.evaluate("id => openTool(id)", tool_id)
    page.wait_for_selector("#frame", timeout=timeout)
    page.wait_for_timeout(700)


def main() -> int:
    args = list(sys.argv[1:])
    base = args.pop(0).rstrip("/") if args and args[0].startswith("http") else DEFAULT_URL
    uid = args[args.index("--as") + 1] if "--as" in args else None
    args = [a for a in args if a != uid and not a.startswith("--")]
    if not args or not uid:
        _p("usage: check_tool_memory.py <challenge_id> --as <uid>")
        return 2
    cid = args[0]

    from testauth import mint

    auth = {"Authorization": "Bearer " + mint(uid)}
    payload = requests.get(f"{base}/api/challenges/{cid}/tools",
                           headers=auth, timeout=90).json()
    tools = payload.get("tools", payload) if isinstance(payload, dict) else payload
    runnable = [t for t in tools if (t.get("type") or "") in RUNNABLE]
    if not runnable:
        _p(f"{cid} has no runnable tool to open")
        return 1
    tool = runnable[0]
    tid = tool["id"]
    value = "logged-" + uuid.uuid4().hex[:8]

    _p(f"target : {base}\ntool   : {tool.get('type')} | {tool.get('name')}\n"
       f"writing: {value}\n")

    bad: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx, page, _ = open_as(browser, base, uid, f"{base}/app?id={cid}")

            open_tool(page, tid)
            seeded = in_frame(page, "() => JSON.stringify(window.__CA_STATE || null)")
            _p(f"1. seeded state handed to the page : {seeded}")
            if seeded is None:
                bad.append("the page was never given a __CA_STATE seed, so a tool that "
                           "reads its log on load would always find nothing")

            # Write the way a tool writes, then close IMMEDIATELY -- inside the 800ms
            # debounce. A user who types their last entry and shuts the modal is the
            # normal case, not the edge case, and it is exactly the one a naive
            # debounce loses.
            in_frame(page, f"() => localStorage.setItem('ca_probe', {value!r})")
            page.evaluate("() => closeTool()")
            _p("2. wrote and closed the modal inside the debounce window")
            page.wait_for_timeout(2500)

            saved = requests.get(f"{base}/api/challenges/{cid}/tools/{tid}/state",
                                 headers=auth, timeout=60).json().get("state") or {}
            _p(f"3. server now holds : {saved}")
            if saved.get("ca_probe") != value:
                bad.append(f"the write never reached the server -- it holds {saved!r}. "
                           "Everything below is measuring a page that kept it in "
                           "memory, which is the failure this check exists to catch")

            # The whole point. Nothing in this page's memory can carry the answer.
            page.reload(wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(3500)
            open_tool(page, tid)
            back = in_frame(page, "() => localStorage.getItem('ca_probe')")
            _p(f"4. after a full reload, the tool reads : {back!r}")
            if back != value:
                bad.append(f"the tool came back empty after a reload (got {back!r}) -- "
                           "which is the entire experience of a tracker that forgets")

            errors = in_frame(page, "() => (window.__CA_STATE && 'ok') || 'missing'")
            _p(f"5. seed on the second open : {errors}")

            # --- every runnable tool, through the REAL dashboard ---------------
            #
            # check_tool_render.py --browser builds its own iframe. It sets srcdoc from
            # JavaScript on an already-inserted element; app.html assigns srcdoc and
            # THEN appends. Close enough to look identical and not close enough to be
            # the same test -- which is how a check ends up measuring its own
            # simulation. This opens each tool the way a person does: the product's own
            # modal, the product's own shim, the product's own state fetch.
            _p("\n--- opening every runnable tool through the dashboard ---")
            page.evaluate("() => closeTool()")
            page.wait_for_timeout(800)
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            for t in [x for x in tools if (x.get("type") or "") in RUNNABLE]:
                before = len(errs)
                open_tool(page, t["id"])
                body = (page.frame_locator("#frame").locator("body").inner_text()
                        or "").strip()
                new = errs[before:]
                _p(f"  {(t.get('name') or '')[:44]:<46} body={len(body):>5}ch "
                   f"errors={len(new)}")
                if new:
                    bad.append(f"{t.get('name')}: threw in the real dashboard -- {new[0][:110]}")
                if not body:
                    bad.append(f"{t.get('name')}: blank in the real dashboard")
                page.evaluate("() => closeTool()")
                page.wait_for_timeout(500)

            # --- the other half: checklist ticks -------------------------------
            # A different code path entirely. Ticks are rendered by the parent page,
            # not by a sandboxed frame, and they used to live in this browser's
            # localStorage -- so a checklist you half-finished on a laptop was blank on
            # a phone, and the app said nothing had been done. Same store now, so the
            # same claim has to hold.
            checklist = next((t for t in tools if t.get("type") == "checklist"), None)
            if not checklist:
                _p("\n(no checklist on this challenge -- ticks unmeasured)")
            else:
                page.evaluate("() => closeTool()")
                page.wait_for_timeout(1500)
                _p(f"\nchecklist: {checklist.get('name')}")
                page.evaluate("id => openTool(id)", checklist["id"])
                page.wait_for_selector("#m-stage .check", timeout=20000)
                page.wait_for_timeout(500)
                boxes = page.locator("#m-stage .check input")
                total = boxes.count()
                boxes.nth(0).check()
                page.evaluate("() => closeTool()")
                _p(f"  ticked box 1 of {total}, closed immediately")
                page.wait_for_timeout(2500)

                page.reload(wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(3500)
                page.evaluate("id => openTool(id)", checklist["id"])
                page.wait_for_selector("#m-stage .check", timeout=20000)
                page.wait_for_timeout(500)
                still = page.locator("#m-stage .check input").nth(0).is_checked()
                _p(f"  after a full reload, box 1 is checked : {still}")
                if not still:
                    bad.append("a checklist tick did not survive a reload -- it is "
                               "still browser-local, or it never saved")
                _clear(base, cid, checklist["id"], auth, bad)
        finally:
            _clear(base, cid, tid, auth, bad)
            browser.close()

    if bad:
        _p("\n--- problems ---")
        for b in bad:
            _p("  * " + b)
        return 1
    _p("\nPASS: a tool remembers across a reload, and a save survives closing the "
       "modal a moment after typing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
