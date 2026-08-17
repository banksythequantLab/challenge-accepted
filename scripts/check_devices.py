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
    # The other side of the 820px breakpoint. `check_a11y` and `check_copy` render at
    # 1500 and 1600; a 13" laptop is 1280 and nothing had drawn one. No touch here, so
    # these also confirm the `hover:none` rules stay off where they should.
    ("Laptop     1280px", None,
     {"viewport": {"width": 1280, "height": 800}}),
    ("Laptop     1440px", None,
     {"viewport": {"width": 1440, "height": 900}}),
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


def _ctx_args(p, name, fallback):  # noqa: D401 -- see below
    """Named profile if this Playwright knows it, otherwise the explicit fallback."""
    if name is None:
        return dict(fallback), None
    return _named(p, name, fallback)


def _named(p, name, fallback):
    """Named profile if this Playwright knows it, otherwise the explicit fallback.

    Device lists change between Playwright versions. A check that dies on an unknown
    name teaches nothing; one that silently skips is worse. This substitutes and says so.
    """
    if name in p.devices:
        return dict(p.devices[name]), None
    if fallback:
        return dict(fallback), f"(no '{name}' profile; used explicit viewport)"
    return None, f"(no '{name}' profile and no fallback -- SKIPPED)"


def _check(page, label, vw, vh, touch: bool) -> list[str]:
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
    # The theme toggle is in this list because it was added to an already-crowded
    # header: one more control on a 320px screen is exactly how the tab row ended up
    # 4px off-screen last time.
    for name, sel in (("Send", "#send"), ("Invite", "#invite"), ("Theme", "#theme")):
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
    # Only where a touch keyboard exists. A mouse-driven laptop never zooms on focus,
    # and 13px is the deliberate desktop size -- flagging it there would be demanding
    # the app be wrong everywhere to be right on phones. This mirrors the CSS exactly:
    # the rule lives in `@media (hover:none)`, so the assertion is scoped to touch too.
    if touch and comp["fs"] < MIN_INPUT_FONT:
        bad.append(f"{label}: the composer is {comp['fs']:.0f}px on a TOUCH device -- "
                   "iOS force-zooms any focused input under 16px and does not zoom back")

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

    # Every side pane, not just the one that happens to be open.
    #
    # This only ever measured the default tab, which meant a control could ship
    # hanging off a 320px screen as long as it lived behind Quest, Journal or Party.
    # The party leave/remove buttons landed in exactly that blind spot -- proven at
    # 1440 by check_party_exit_ui.py and measured nowhere narrower.
    seen = {}
    for pane in ("quest", "journal", "facts"):
        page.click(f"[data-p='{pane}']")
        page.wait_for_timeout(250)
        measured, off = page.evaluate(
            """() => {
                 const out = [];
                 let n = 0;
                 for (const el of document.querySelectorAll('.pane.on button, .pane.on a')) {
                   const r = el.getBoundingClientRect();
                   if (!r.width) continue;
                   n++;
                   if (r.right > window.innerWidth + 1 || r.left < -1)
                     out.push('offscreen ' + el.textContent.trim().slice(0, 24));
                   // 32px is the floor a previous run of this check established, after
                   // a 28px theme toggle shipped and nothing noticed.
                   if (r.height < 32 && el.offsetParent !== null)
                     out.push('tap target ' + Math.round(r.height) + 'px: '
                              + el.textContent.trim().slice(0, 24));
                 }
                 return [n, out];
               }""")
        seen[pane] = measured
        if off:
            bad.append(f"{label}: {pane} pane -- {off}")
    # Printed because a pane with nothing in it passes every assertion above by having
    # nothing to measure, and reads identically to a pane that was checked. If `facts`
    # says 1 you are looking at Invite alone and the leave/remove controls did not
    # render -- which means this run said nothing about them.
    _p(f"    pane controls: " + ", ".join(f"{k} {v}" for k, v in seen.items()))
    page.click("[data-p='chat']")
    page.wait_for_timeout(200)

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


def _live_challenge(base: str, uid: str | None, cid: str | None) -> str:
    """A real challenge from the deployed API -- one with tools, so the map is populated.

    An empty dashboard would pass every assertion here by having nothing to lay out.

    Since Google Sign-In shipped this needs a token, and the quest list is scoped to
    the caller: a brand-new test identity legitimately sees nothing, so discovering a
    challenge means signing in as an identity that owns one. Pass `--as <uid>` for
    that, or `--challenge <id>` to name one outright.
    """
    import requests

    from testauth import mint

    base = base.rstrip("/")
    headers = {}
    if requests.get(f"{base}/api/healthz", timeout=30).json().get("auth") == "required":
        headers = {"Authorization": "Bearer " + mint(uid)}
        print(f"signed in as {uid or 'a fresh test identity'} to look for a challenge")

    def populated(challenge_id: str) -> tuple[int, int] | None:
        r = requests.get(f"{base}/api/challenges/{challenge_id}/dashboard",
                         headers=headers, timeout=60)
        if not r.ok:
            print(f"  {challenge_id}: dashboard {r.status_code} "
                  f"{'(not a member)' if r.status_code == 403 else ''}")
            return None
        dash = r.json()
        tools = dash.get("tools")
        tools = (tools.get("tools") if isinstance(tools, dict) else tools) or []
        nodes = (dash.get("graph") or {}).get("nodes") or []
        return (len(nodes), len(tools)) if nodes and tools else None

    if cid:
        counts = populated(cid)
        if not counts:
            sys.exit(f"FAIL: {cid} is not readable by this identity, or has no map. "
                     f"Pass --as <uid> for an account that is on its party.")
        print(f"live challenge: {cid}  ({counts[0]} nodes, {counts[1]} tools)")
        return cid

    rows = requests.get(f"{base}/api/challenges?limit=25", headers=headers,
                        timeout=60).json().get("challenges", [])
    for row in rows:
        counts = populated(row["id"])
        if counts:
            print(f"live challenge: {row['id']}  ({counts[0]} nodes, {counts[1]} tools)")
            return row["id"]
    sys.exit("FAIL: no challenge this identity can read has both nodes and tools. "
             "Pass --challenge <id> and --as <uid>.")


def main(base: str | None = None, uid: str | None = None,
         cid_arg: str | None = None) -> None:
    if base:
        cid = _live_challenge(base, uid, cid_arg)
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
            # A deployed page now opens on the sign-in gate, and an invite link opens
            # on a join button. Both are the product working correctly, and both would
            # otherwise be measured as "the map rendered no nodes".
            if page.is_visible("#gate"):
                from testauth import sign_in
                sign_in(page, uid)
            join = page.get_by_role("button", name="Join this quest")
            if join.count():
                join.first.click()
                page.wait_for_timeout(2500)
            # Wait for the MAP, not for a stopwatch. A fixed 1000ms was enough on a
            # warm local server and not enough for the first device to hit production
            # cold -- so the Galaxy S9+ reported "the quest map rendered no nodes" on a
            # challenge that has twelve, and the six devices after it passed. A flaky
            # check that blames the product is worse than no check.
            try:
                page.wait_for_selector("#graph .node", timeout=30000)
            except Exception:
                pass          # let the assertion below report it properly
            page.wait_for_timeout(600)
            vw = page.viewport_size["width"]
            vh = page.viewport_size["height"]
            _p(f"    viewport     : {vw}x{vh}")

            touch = bool(args.get("has_touch") or args.get("hasTouch"))
            _p(f"    touch        : {touch}")
            failures += _check(page, label, vw, vh, touch)
            if errors:
                failures.append(f"{label}: console errors {errors}")
            _p(f"    console      : {errors if errors else 'clean'}")

            # Both themes, on every device. The theme changes no geometry, so the
            # assertions above run once -- but the screenshots are the only thing that
            # has ever caught a colour that stopped being readable at a given size,
            # and light mode has never been seen on a phone.
            shots = ROOT / "_walk"
            shots.mkdir(exist_ok=True)
            for theme in ("dark", "light"):
                page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                page.wait_for_timeout(300)
                page.screenshot(path=str(shots / f"dev_{vw}_{theme}.png"))
            ctx.close()
        browser.close()

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    where = origin if origin.startswith("https") else "a local server"
    _p(f"\nthe layout holds on all {len(DEVICES)} viewports, on {where}, in both "
       f"themes. wrote _walk/dev_*.png")


if __name__ == "__main__":
    argv = sys.argv[1:]

    def take(flag: str) -> str | None:
        if flag in argv:
            i = argv.index(flag)
            v = argv[i + 1]
            del argv[i:i + 2]
            return v
        return None

    who = take("--as")
    which = take("--challenge")
    main(argv[0] if argv else None, who, which)
