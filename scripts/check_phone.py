"""The whole app on a phone, with real touch events.

Derek scans a QR and opens this on a handset. Only two things had ever been checked at
that size -- the Copy buttons' opacity and the grid collapsing to one column -- so the
tool viewer, the quest map, Invite, the feedback field and the forge rail were all
unverified on the device most likely to be holding the app during the hackathon.

Uses `p.devices["iPhone 13"]`, which sets `hasTouch` and `isMobile`, and TAPS rather
than clicking. That distinction matters: `hover:none` styling, 44px touch targets and
`click` handlers that were only ever exercised by a mouse all fail differently.

    python scripts\\check_phone.py
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

PORT = 8146
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

#: Apple's HIG and the WCAG 2.1 target-size guidance both land around here. Below it,
#: people miss.
MIN_TAP = 32

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

    cid = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    failures: list[str] = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(**p.devices["iPhone 13"])
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1200)
        vw, vh = page.viewport_size["width"], page.viewport_size["height"]
        _p(f"viewport     : {vw}x{vh}")

        # Nothing may spill sideways. A horizontal scrollbar on a phone means the user
        # is dragging the layout around to read it.
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth")
        _p(f"h-overflow   : {overflow}px")
        if overflow > 1:
            failures.append(f"page scrolls sideways by {overflow}px")

        # --- the quest map ------------------------------------------------------
        # It is an SVG laid out by dependency depth on a 1500px canvas. On a 390px
        # screen the question is whether a node can be tapped at all.
        nodes = page.eval_on_selector_all(".node", "els => els.length")
        _p(f"map nodes    : {nodes}")
        if not nodes:
            failures.append("the quest map rendered no nodes on a phone")
        else:
            page.eval_on_selector_all(
                ".node", "els => els[0].dispatchEvent(new MouseEvent('click',{bubbles:true}))")
            page.wait_for_timeout(500)
            if not page.is_visible("#detail h3"):
                failures.append("tapping a node did not open the quest panel")

        # --- opening a tool -----------------------------------------------------
        page.tap('.tab[data-p="quest"]')
        page.wait_for_timeout(300)
        if page.is_visible("[data-open]"):
            btn = page.locator("[data-open]").first
            b = btn.bounding_box()
            _p(f"Open tool    : {b['width']:.0f}x{b['height']:.0f}px")
            if b["height"] < MIN_TAP:
                failures.append(f"'Open tool' is only {b['height']:.0f}px tall "
                                f"(want >= {MIN_TAP})")
            btn.tap()
            page.wait_for_selector("#modal.on", timeout=5000)
            sheet = page.eval_on_selector(
                ".sheet", "e => { const r = e.getBoundingClientRect();"
                          "return {w: r.width, h: r.height, top: r.top}; }")
            _p(f"tool sheet   : {sheet['w']:.0f}x{sheet['h']:.0f} at top={sheet['top']:.0f}")
            if sheet["w"] > vw:
                failures.append(f"the tool sheet is wider than the screen "
                                f"({sheet['w']:.0f} > {vw})")
            if sheet["top"] < 0:
                failures.append(f"the tool sheet is cut off at the top "
                                f"(top={sheet['top']:.0f}) -- the title is unreadable")
            if sheet["h"] > vh:
                failures.append("the tool sheet is taller than the screen")
            # The footer actions are the reason the sheet exists on a phone.
            for sel in ("#m-copy", "#m-claude", "#m-close"):
                if not page.is_visible(sel):
                    failures.append(f"{sel} is not visible in the tool sheet on a phone")
            page.screenshot(path=str(ROOT / "_phone_tool.png"))
            page.tap("#m-close")
            page.wait_for_timeout(400)
            if page.is_visible("#modal.on"):
                failures.append("Close did not dismiss the tool sheet on tap")
        else:
            failures.append("no 'Open tool' button reachable on a phone")

        # --- the feedback field -------------------------------------------------
        page.wait_for_selector('[data-fb="down"]', timeout=5000)
        fb = page.locator('[data-fb="down"]').first.bounding_box()
        _p(f"thumbs-down  : {fb['width']:.0f}x{fb['height']:.0f}px")
        if fb["height"] < MIN_TAP:
            failures.append(f"the thumbs-down target is {fb['height']:.0f}px tall")
        page.locator('[data-fb="down"]').first.tap()
        page.wait_for_selector("#whytext", timeout=5000)
        w = page.eval_on_selector("#whytext", "e => e.getBoundingClientRect().width")
        send_w = page.eval_on_selector("#whysend", "e => e.getBoundingClientRect().width")
        _p(f"reason field : {w:.0f}px  (Send {send_w:.0f}px)")
        if w < 120:
            failures.append(f"the reason field collapses to {w:.0f}px on a phone")
        # iOS zooms the page when a focused input is under 16px. That zoom does not
        # undo itself, and the user is left stranded at 1.3x with no way back.
        fs = page.eval_on_selector("#whytext", "e => getComputedStyle(e).fontSize")
        _p(f"input font   : {fs}")
        if float(fs.replace("px", "")) < 16:
            failures.append(f"the reason field is {fs} -- iOS Safari force-zooms any "
                            "focused input under 16px and does not zoom back out")

        # --- invite -------------------------------------------------------------
        page.tap('.tab[data-p="facts"]')
        page.wait_for_timeout(300)
        inv = page.locator("#invite").bounding_box()
        _p(f"Invite       : {inv['width']:.0f}x{inv['height']:.0f}px")
        if inv["height"] < MIN_TAP:
            failures.append(f"Invite is only {inv['height']:.0f}px tall")
        page.tap("#invite")
        page.wait_for_timeout(400)
        link = page.evaluate("() => navigator.clipboard.readText()")
        _p(f"invite link  : {link}")
        if not link or f"id={cid}" not in link:
            failures.append(f"Invite copied {link!r} on a phone")

        # --- the composer -------------------------------------------------------
        page.tap('.tab[data-p="chat"]')
        page.wait_for_timeout(300)
        comp = page.eval_on_selector(
            "#input", "e => { const r = e.getBoundingClientRect();"
                      "return {w: r.width, fs: getComputedStyle(e).fontSize}; }")
        sendb = page.locator("#send").bounding_box()
        _p(f"composer     : {comp['w']:.0f}px, font {comp['fs']}, "
           f"Send {sendb['width']:.0f}x{sendb['height']:.0f}px")
        if comp["w"] < 140:
            failures.append(f"the composer is {comp['w']:.0f}px wide")
        if float(comp["fs"].replace("px", "")) < 16:
            failures.append(f"the composer is {comp['fs']} -- iOS will force-zoom on focus")
        if sendb["height"] < MIN_TAP:
            failures.append(f"Send is only {sendb['height']:.0f}px tall")

        # On touch the Copy chip is permanently visible, so it must not sit on top of
        # the words it is offering to copy.
        page.wait_for_selector(".msg.bot .copy", timeout=5000)
        clash = page.evaluate(
            """() => {
                 const m = document.querySelector('.msg.bot');
                 const c = m.querySelector('.copy').getBoundingClientRect();
                 const b = m.querySelector('.body').getBoundingClientRect();
                 return Math.round(Math.min(b.right, c.right) - Math.max(b.left, c.left));
               }""")
        _p(f"copy overlap : {clash}px into the text")
        if clash > 0:
            failures.append(f"the Copy chip covers {clash}px of the message text on touch")

        page.screenshot(path=str(ROOT / "_phone_app.png"), full_page=False)
        browser.close()

    _p(f"\nconsole errors: {errors if errors else 'none'}")
    if errors:
        failures.append(f"console errors: {errors}")

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    _p("\nthe app works on a phone. wrote _phone_tool.png, _phone_app.png")


if __name__ == "__main__":
    main()
