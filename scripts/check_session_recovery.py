"""Prove the dashboard survives losing its session, the way a Cloud Run restart does.

Sessions are held in server memory until an Agent Engine backs them. When Cloud Run
recycles an instance -- which it will, repeatedly, across weeks of judging -- the
browser is left holding a sessionId the server has never heard of.

This boots the real app, takes one turn, DELETEs the session out from under the
page (identical symptom to a restart), then takes another turn. It passes only if
the second turn still gets an answer.

    python scripts\\check_session_recovery.py
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

import requests  # noqa: E402
import uvicorn  # noqa: E402

from main import app  # noqa: E402

PORT = 8143
APP_NAME = "challenge_accepted"


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def main() -> None:
    import socket

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    threading.Thread(target=serve, daemon=True).start()
    time.sleep(3.0)

    base = f"http://127.0.0.1:{PORT}"
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"{base}/app", wait_until="networkidle")
        page.wait_for_timeout(1200)

        def turn(text: str) -> int:
            page.fill("#input", text)
            page.click("#send")
            page.wait_for_function("() => !document.getElementById('send').disabled",
                                   timeout=300_000)
            page.wait_for_timeout(600)
            return page.eval_on_selector_all(".msg.bot", "els => els.length")

        before = turn("I want to learn to bake sourdough.")
        _p(f"turn 1: {before} bot bubbles")

        # Whose session is it? Read it back from the URL the page is talking to.
        sid = page.evaluate("""() => {
          const e = performance.getEntriesByType('resource')
            .map(r => r.name).filter(n => n.includes('/sessions/')).pop();
          return e ? e.split('/sessions/')[1] : null;
        }""")
        user = page.evaluate("() => localStorage.getItem('ca_user')")
        _p(f"session: {sid}  user: {user}")
        if not sid:
            sys.exit("FAIL: could not determine the session id")

        # Pull the session out from under the page. Same symptom as a restart.
        d = requests.delete(f"{base}/apps/{APP_NAME}/users/{user}/sessions/{sid}")
        _p(f"DELETE session -> {d.status_code}")
        gone = requests.get(f"{base}/apps/{APP_NAME}/users/{user}/sessions/{sid}")
        _p(f"GET  session -> {gone.status_code} (should not be 200)")
        if gone.status_code == 200:
            sys.exit("FAIL: session survived the delete, so this proves nothing")

        after = turn("Actually, make it focaccia instead.")
        _p(f"turn 2: {after} bot bubbles")

        texts = page.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        acts = page.eval_on_selector_all(".msg.act", "els => els.map(e => e.innerText)")
        browser.close()

    _p("\nlast reply: " + texts[-1][:200].replace("\n", " "))
    broke = [a for a in acts if "run_sse" in a or "session create failed" in a]
    _p(f"error chips : {broke if broke else 'none'}")
    _p(f"page errors : {errors if errors else 'none'}")

    if after <= before or broke:
        sys.exit("FAIL: the page did not recover from losing its session")
    _p("\nrecovered from a lost session without a reload")


if __name__ == "__main__":
    main()
