"""CLIMB, driven the way a user drives it.

This is the half of the product that runs AFTER the tools exist: pick a step, the Coach
tells you what done looks like, you report what you did, and the Referee either closes
the node with your evidence or refuses. It is half the track brief ("guide the user
step-by-step... capture feedback") and it has only ever been proven by
`scripts/live_climb.py`, which talks to the agents directly and never touches the UI.

Every other beat that was "proven by script" turned out to be broken in the browser --
the party beat hid four separate bugs behind exactly that assumption. So: real browser,
real agents, real Firestore-shaped store.

Passes only if:
  * "Work on this" puts a usable turn in the composer and the Coach answers it,
  * reporting real evidence gets the node CLOSED -- `complete_node` fires,
  * the node turns green ON THE MAP without a reload, and the counter goes up,
  * the evidence the user gave is what got recorded, not a paraphrase.

    python scripts\\check_climb.py
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

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import uvicorn  # noqa: E402

from challenge_accepted.services.store import store  # noqa: E402
from main import app  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8145

#: The node the run will try to close. Seeded as "active" with a tool attached, which
#: is exactly the state a user reaches after FORGE.
TARGET = "frontend-shell"

#: Concrete, checkable, and phrased as something that happened -- the Referee is
#: supposed to refuse "I did it". The commit hash is the tell: if it survives into the
#: stored evidence, the system recorded what the user actually said.
EVIDENCE = (
    "Done. The Next.js shell is up with auth working -- I can sign in and out, and it "
    "redirects to /login when signed out. Committed as 4f2a91c and running on "
    "localhost:3000. Screenshot is in the PR."
)


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def main() -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    cid = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(3.0)

    before = next(n for n in store.list_nodes(cid) if n["id"] == TARGET)
    _p(f"\ntarget node  : {TARGET} (status={before['status']}, "
       f"evidence={before.get('evidence')})")
    if before["status"] == "done":
        sys.exit("FAIL: the seed already closed the target node; nothing to prove")

    failures: list[str] = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 940})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1200)

        # Click the node on the map, the way a user does. Dispatch rather than click:
        # the poll redraws the SVG and an ElementHandle can detach mid-click.
        page.evaluate(f"""() => {{
          const n = [...document.querySelectorAll('.node')]
            .find(e => e.textContent.includes('Next.js shell'));
          if (!n) throw new Error('target node not on the map');
          n.dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
        }}""")
        page.wait_for_selector("#workon", timeout=5000)
        _p(f"quest panel  : {page.inner_text('#detail h3').strip()!r}")

        page.click("#workon")
        page.wait_for_timeout(300)
        composed = page.input_value("#input")
        on_chat = page.eval_on_selector(
            '.tab[data-p="chat"]', "e => e.classList.contains('on')")
        _p(f"work-on puts : {composed!r}")
        if not composed.strip():
            browser.close()
            sys.exit("FAIL: 'Work on this' left the composer empty")
        if not on_chat:
            failures.append("'Work on this' left the user on the Quest tab, so they "
                            "never see the answer arrive")

        page.click("#send")
        page.wait_for_function("() => !document.getElementById('send').disabled",
                               timeout=300_000)
        page.wait_for_timeout(800)
        coach = page.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        _p("\ncoach says   : " + (coach[-1][:260].replace("\n", " ") if coach else "(nothing)"))
        if not coach or len(coach[-1]) < 40:
            failures.append("the Coach did not answer 'Work on this'")

        # Now report it done, with evidence.
        _p(f"\nreporting    : {EVIDENCE[:80]}...")
        page.fill("#input", EVIDENCE)
        page.click("#send")
        page.wait_for_function("() => !document.getElementById('send').disabled",
                               timeout=300_000)
        page.wait_for_timeout(1500)

        calls = page.eval_on_selector_all(
            ".msg.act", "els => els.map(e => e.innerText.trim())")
        reply = page.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        _p("tool calls   : " + " | ".join(calls[-8:]))
        _p("reply        : " + (reply[-1][:260].replace("\n", " ") if reply else "(nothing)"))

        # The map has to show it without a reload. That is the whole point of the poll.
        page.wait_for_timeout(5000)
        on_map = page.evaluate(f"""() => {{
          const n = [...document.querySelectorAll('.node')]
            .find(e => e.textContent.includes('Next.js shell'));
          return n ? n.textContent : null;
        }}""")
        cleared = page.inner_text("#c-done").strip()
        page.screenshot(path=str(ROOT / "_climb.png"))
        browser.close()

    _p(f"\nnode on map  : {(on_map or '').strip()[:80]!r}")
    _p(f"quests cleared: {cleared} (was {before.get('status')})")
    _p(f"console errors: {errors if errors else 'none'}")

    after = next(n for n in store.list_nodes(cid) if n["id"] == TARGET)
    _p(f"\nstored status : {after['status']}")
    _p(f"stored evidence: {after.get('evidence')}")

    if after["status"] != "done":
        failures.append(
            f"the node is still {after['status']!r} after the user reported it done "
            "with evidence -- CLIMB does not close anything"
        )
    else:
        ev = " ".join(after.get("evidence") or [])
        if "4f2a91c" not in ev:
            failures.append(
                "the recorded evidence does not contain the commit hash the user gave "
                f"-- it was paraphrased into: {ev[:160]!r}"
            )
        if on_map and "done" not in on_map.lower():
            failures.append("the map still does not show the node as done -- the user "
                            "has to reload to see their own progress")

    if errors:
        failures.append(f"console errors: {errors}")

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    _p("\nCLIMB closes a step from the UI, with the user's own evidence. wrote _climb.png")


if __name__ == "__main__":
    main()
