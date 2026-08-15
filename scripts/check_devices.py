"""Does the layout hold on the devices nobody has ever opened this on?

`check_phone.py` drives the whole product deeply on **one** handset: iPhone 13. That is
the device most likely to be holding the app during the hackathon, and it earns the
depth. But it is one 390px Android-free data point, and the dashboard has exactly two
breakpoints -- `max-width:820px` and `hover:none`. Everything between 820px and a
desktop window has never been rendered by anything.

So this trades depth for breadth: the same layout assertions, across five viewports that
bracket the real ones.

  * **Galaxy S9+ (320px)** -- the narrowest screen anyone still uses. If a fixed width
    is going to cause sideways scroll, it shows here first.
  * **iPhone 13 (390px)** -- the reference handset, kept so a regression here is caught
    by both checks.
  * **Pixel 7 (412px)** -- Android. Chrome on Android, not Safari; different default
    font metrics and a different clipboard story.
  * **iPad Mini portrait (768px)** -- *under* the 820px breakpoint, so it gets the phone
    layout on a tablet-sized screen. Worth knowing whether that looks deliberate.
  * **iPad landscape (1024px)** -- **the hole.** Above the breakpoint, far below the
    1500px the desktop checks use. Nothing has ever rendered this width.

Layout is a client concern: the HTML served locally is the same single file production
serves, so testing it locally is legitimate in a way it is not for agent behaviour. But
"the same file" is an assumption, and this project has been bitten hard by exactly that
class of assumption -- FORGE passed locally for weeks while building nothing in
production. So pass a URL and it renders the deployed page instead, on the same five
viewports, against a real challenge pulled from the live API.

    python scripts\\check_devices.py                            # local, seeded
    python scripts\\check_devices.py https://challengeaccepted.app   # the deployed page

Exit 0 only if every viewport passes every assertion.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from challenge_accepted.api import router  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8151
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

#: Apple's HIG and WCAG 2.1 target-size guidance both land around here.
MIN_TAP = 32

#: iOS Safari force-zooms a focused input under 16px and never zooms back.
MIN_INPUT_FONT = 16

#: (label, playwright device name, fallback context args). Named devices carry
#: `hasTouch`/`isMobile`, which change hit-testing and `hover:none` styling -- a plain
#: viewport resize does not, and would quietly test something else.
DEVICES = [
    ("Galaxy S9+  320px", "Galaxy S9+", None),
    ("iPhone 13   390px", "iPhone 13", None),
    ("Pixel 7     412px", "Pixel 7", None),
    ("iPad Mini   768px", "iPad Mini", None),
    ("iPad land. 1024px", "iPad (gen 7) landscape",
     {"viewport": {"width": 1024, "height": 768}, "has_touch": True, "is_mobile": False}),
]

app = FastAPI()
app.include_router(router)


@app.get("/app")
def dashboard() -> FileResponse:
    return FileResponse(STATIC)


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def _ctx_args(p, name, fallback):
    """Named profile if this Playwright knows it, otherwise the explicit fallback.

    Device lists change between Playwright versions. A check that dies on an unknown
    name teaches nothing; one that silently skips is worse. This substitutes and says so.
    """
    if name in p.devices:
        return dict(p.devices[name]), None
    if fallback:
        return dict(fallback), f"(no '{name}' profile; used explicit viewport)"
    return None, f"(no '{name}' profile and no fallback -- SKIPPED)"


def _check(page, label, vw, vh) -> list[str]:
    bad: list[str] = []

    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth")
    _p(f"    h-overflow   : {overflow}px")
    if overflow > 1:
        bad.append(f"{label}: scrolls sideways by {overflow}px")

    nodes = page.eval_on_selector_all(".node", "els => els.length")
    _p(f"    map nodes    : {nodes}")
    if not nodes:
        bad.append(f"{label}: the quest map rendered no nodes")

    # Every control a finger has to hit. A 20px button is a miss, not a tap.
    for name, sel in (("Send", "#send"), ("Invite", "#invite")):
        if page.is_visible(sel):
            box = page.locator(sel).first.bounding_box()
            if box and box["height"] < MIN_TAP:
                bad.append(f"{label}: {name} is {box['height']:.0f}px tall "
                           f"(want >= {MIN_TAP})")

    # The composer is the one input on every screen, and the one iOS will zoom.
    comp = page.eval_on_selector(
        "#input", "e => { const r = e.getBoundingClientRect();"
                  "return {w: r.width, fs: parseFloat(getComputedStyle(e).fontSize)}; }")
    _p(f"    composer     : {comp['w']:.0f}px, font {comp['fs']:.0f}px")
    if comp["w"] < 140:
        bad.append(f"{label}: the composer collapses to {comp['w']:.0f}px")
    if comp["fs"] < MIN_INPUT_FONT:
        bad.append(f"{label}: the composer is {comp['fs']:.0f}px -- iOS force-zooms "
                   "any focused input under 16px and does not zoom back")

    # Text that does not fit its own box. Every numeric assertion above passed while
    # the composer greeted the user with a sentence cut in half -- the placeholder
    # wrapped to two lines inside a one-line textarea, and only the screenshots showed
    # it. A width in pixels tells you nothing about whether the words fit.
    clipped = page.evaluate(
        """() => {
             const out = [];
             for (const el of document.querySelectorAll('#input,.msg .body,#title')) {
               if (el.scrollHeight > el.clientHeight + 2)
                 out.push((el.id || el.className) + ' needs ' + el.scrollHeight +
                          'px, has ' + el.clientHeight);
             }
             return out;
           }""")
    _p(f"    clipped text : {clipped if clipped else 'none'}")
    if clipped:
        bad.append(f"{label}: text cut off by its own box -- {clipped}")

    # Nothing may hang off the bottom or the right of the viewport.
    spill = page.evaluate(
        """() => {
             const out = [];
             for (const el of document.querySelectorAll('#input,#send,#invite,.tab')) {
               const r = el.getBoundingClientRect();
               if (r.width && (r.right > window.innerWidth + 1 || r.left < -1))
                 out.push((el.id || el.className) + ' x:' + Math.round(r.left) +
                          '-' + Math.round(r.right));
             }
             return out;
           }""")
    if spill:
        bad.append(f"{label}: controls outside the viewport -- {spill}")
    return bad


def _live_challenge(base: str) -> str:
    """A real challenge from the deployed API -- one with tools, so the map is populated.

    An empty dashboard would pass every assertion here by having nothing to lay out.
    """
    import json
    import urllib.request

    with urllib.request.urlopen(base.rstrip("/") + "/api/challenges?limit=25",
                                timeout=30) as r:
        rows = json.load(r)
    rows = rows if isinstance(rows, list) else rows.get("challenges", [])
    for row in rows:
        url = f"{base.rstrip('/')}/api/challenges/{row['id']}/dashboard"
        with urllib.request.urlopen(url, timeout=30) as r:
            dash = json.load(r)
        tools = dash.get("tools")
        tools = (tools.get("tools") if isinstance(tools, dict) else tools) or []
        nodes = (dash.get("graph") or {}).get("nodes") or []
        if tools and nodes:
            print(f"live challenge: {row['id']}  ({len(nodes)} nodes, {len(tools)} tools)")
            return row["id"]
    sys.exit("FAIL: no deployed challenge has both nodes and tools to lay out.")


def main(base: str | None = None) -> None:
    if base:
        cid = _live_challenge(base)
        origin = base.rstrip("/")
    else:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")
        cid = seed()
        threading.Thread(target=serve, daemon=True).start()
        time.sleep(2.0)
        origin = f"http://127.0.0.1:{PORT}"

    failures: list[str] = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, name, fallback in DEVICES:
            args, note = _ctx_args(p, name, fallback)
            _p(f"\n=== {label} {note or ''}")
            if args is None:
                failures.append(f"{label}: {note}")
                continue

            ctx = browser.new_context(**args)
            page = ctx.new_page()
            errors: list[str] = []
            page.on("console",
                    lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))

            page.goto(f"{origin}/app?id={cid}", wait_until="networkidle")
            page.wait_for_timeout(1000)
            vw = page.viewport_size["width"]
            vh = page.viewport_size["height"]
            _p(f"    viewport     : {vw}x{vh}")

            failures += _check(page, label, vw, vh)
            if errors:
                failures.append(f"{label}: console errors {errors}")
            _p(f"    console      : {errors if errors else 'clean'}")

            shot = ROOT / f"_dev_{vw}.png"
            page.screenshot(path=str(shot))
            ctx.close()
        browser.close()

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    where = origin if origin.startswith("https") else "a local server"
    _p(f"\nthe layout holds on all {len(DEVICES)} viewports, on {where}. wrote _dev_*.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
