"""End-to-end proof that the dashboard chat actually drives the agents.

Boots the REAL app (main.py -> get_fast_api_app, so /run_sse and the session
endpoints are live), opens /app in a headless browser, types a goal into the
chat box, clicks Send, and waits for the agent to answer.

Passes only if:
  * a bot bubble with real text appears (the agents replied), and
  * the header title stops being the placeholder (challenge_id was adopted).

    python scripts\\drive_chat.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import uvicorn  # noqa: E402

from main import app  # noqa: E402

PORT = 8139

#: A whole interview in four turns. The last one tells Warden to stop asking and
#: commit, which is what forces the charter -- and therefore challenge_id -- to exist.
TURNS = [
    "I want to run a 10k in under 55 minutes by Christmas.",
    "I run about 3k twice a week at a slow pace. Nothing has held me back, "
    "I just have never trained properly.",
    "I can train four evenings a week, about 45 minutes each. Success is crossing "
    "the line at the Christmas Eve park 10k under 55 minutes.",
    "That's everything -- accept the challenge and draw me the map.",
]


def _p(s: str) -> None:
    """Windows console is cp1252; the UI legitimately uses emoji."""
    print(s.encode("ascii", "replace").decode("ascii"))


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def main() -> None:
    # A leftover server from a previous run would silently answer instead of this
    # one, and you would be testing stale state. Refuse rather than mislead.
    import socket

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    threading.Thread(target=serve, daemon=True).start()
    time.sleep(3.0)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950},
                                device_scale_factor=2)
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"http://127.0.0.1:{PORT}/app", wait_until="networkidle")
        page.wait_for_timeout(1200)

        for turn in TURNS:
            page.fill("#input", turn)
            page.click("#send")
            _p(f"\n>>> {turn}")
            # Send re-enables only after the whole SSE stream closes.
            page.wait_for_function("() => !document.getElementById('send').disabled",
                                   timeout=300_000)
            page.wait_for_timeout(800)
            _p("    ...answered, title now: " + repr(page.inner_text("#title")))

        page.wait_for_timeout(2000)
        page.screenshot(path=str(ROOT / "_chat.png"))

        bubbles = page.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        acts = page.eval_on_selector_all(".msg.act", "els => els.map(e => e.innerText.trim())")
        title = page.inner_text("#title")
        placeholder = page.eval_on_selector("#title", "e => e.classList.contains('empty')")
        nodes = page.eval_on_selector_all(".node", "els => els.length")
        cid = page.evaluate("() => new URLSearchParams(location.search).get('id')")
        browser.close()

    _p("\n--- bot bubbles ---")
    for b in bubbles:
        _p(" * " + b[:300].replace("\n", " "))
    _p("\n--- tool calls / code ---")
    for a in acts:
        _p(" * " + a)
    _p(f"\nchallenge id    : {cid}")
    _p(f"title           : {title!r} (placeholder={placeholder})")
    _p(f"quest nodes     : {nodes}")
    _p(f"console errors  : {errors if errors else 'none'}")

    replied = len(bubbles) > 1 and len(bubbles[-1]) > 20
    _p(f"\nagent replied   : {replied}")
    _p(f"title filled in : {not placeholder}")
    _p("wrote _chat.png")
    if not replied:
        sys.exit("FAIL: no agent reply came back through the chat panel")
    if placeholder:
        sys.exit("FAIL: challenge_id never reached the UI -- title still placeholder")
    if not cid:
        sys.exit("FAIL: adoptChallengeFromSession never picked up challenge_id")


if __name__ == "__main__":
    main()
