"""Prove the copy-to-Claude buttons actually put the right text on the clipboard.

Seeds demo data, serves the real read API, then in a headless browser clicks each
copy affordance and reads the clipboard back. Asserts on content, not on the button
changing colour -- a button that says "Copied" while the clipboard is empty is
exactly the kind of thing this repo does not ship.

    python scripts\\check_copy.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from challenge_accepted.api import router  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8141
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

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
    import socket

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    cid = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    from playwright.sync_api import sync_playwright

    failures: list[str] = []

    def check(label: str, text: str, must_contain: list[str]) -> None:
        _p(f"\n--- {label} ({len(text)} chars) ---")
        _p(text[:400] + ("..." if len(text) > 400 else ""))
        for needle in must_contain:
            if needle.lower() not in text.lower():
                failures.append(f"{label}: missing {needle!r}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1600, "height": 950})
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Name the challenge explicitly. A bare /app no longer auto-selects the newest
        # quest in the store -- on a shared URL that dropped the second visitor into the
        # first visitor's goal -- so a probe that relied on that was testing a default
        # that should never have existed.
        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1500)

        read = lambda: page.evaluate("() => navigator.clipboard.readText()")

        # 1. A quest that actually has a tool attached, so the source gets included.
        # Dispatch rather than a real click: the 4s poll redraws the SVG, so an
        # ElementHandle can detach mid-click. The badge also swallows pointer events.
        page.evaluate("""() => {
          const n = [...document.querySelectorAll('.node')]
            .find(e => e.querySelector('circle')) || document.querySelector('.node');
          n.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        }""")
        page.wait_for_timeout(500)

        page.click("#forclaude")
        page.wait_for_timeout(400)
        check("Copy for Claude", read(),
              ["i'm working toward", "the step i'm on", "cleared when"])

        # "Copy tool" now lives in the tool viewer, so open it first.
        if page.query_selector("[data-open]"):
            page.click("[data-open]")
            page.wait_for_timeout(500)
            page.click("#m-copy")
            page.wait_for_timeout(400)
            check("Copy tool", read(), ["#"])
            page.click("#m-close")
            page.wait_for_timeout(300)
        else:
            failures.append("Copy tool: no tool button rendered on this quest")

        # 2. The greeting bubble is a bot message, so it carries a Copy button.
        page.click('.tab[data-p="chat"]')
        page.wait_for_timeout(300)
        page.hover("#chatlog .msg.bot")
        page.click("#chatlog .msg.bot .copy")
        page.wait_for_timeout(400)
        check("Copy message", read(), ["tell me something you want"])

        page.click("#copyall")
        page.wait_for_timeout(400)
        check("Copy all", read(), ["## warden"])

        # 3. Phone. Reveal-on-hover would hide Copy entirely on a touch screen,
        # and that is the case where copying into another app matters most.
        phone = browser.new_context(**p.devices["iPhone 13"])
        phone.grant_permissions(["clipboard-read", "clipboard-write"])
        pp = phone.new_page()
        pp.on("pageerror", lambda e: errors.append("phone: " + str(e)))
        pp.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        pp.wait_for_timeout(1500)
        opacity = pp.eval_on_selector(
            "#chatlog .msg.bot .copy", "e => getComputedStyle(e).opacity")
        _p(f"\nphone copy-button opacity : {opacity}")
        if float(opacity) < 0.3:
            failures.append(f"phone: Copy button invisible (opacity {opacity})")
        stacked = pp.eval_on_selector(
            "#app", "e => getComputedStyle(e).gridTemplateColumns")
        _p(f"phone grid columns        : {stacked}")
        if len(stacked.split()) > 1:
            failures.append(f"phone: layout still multi-column ({stacked})")
        pp.screenshot(path=str(ROOT / "_phone.png"), full_page=False)
        _p("wrote _phone.png")

        browser.close()

    _p(f"\nconsole errors  : {errors if errors else 'none'}")
    if errors:
        failures.append(f"console errors: {errors}")
    if failures:
        _p("\nFAILURES:")
        for f in failures:
            _p("  * " + f)
        sys.exit(1)
    _p("\nall copy affordances put the right text on the clipboard")


if __name__ == "__main__":
    main()
