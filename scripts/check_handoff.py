"""What a joining teammate actually gets handed.

The README has carried one row reading "Not verified" for weeks:

    That a joining teammate is never offered an already-`done` node. The check exists
    but was vacuous -- Derek hit a blocker rather than completing anything in that
    script.

That is the failure mode with the worst optics in the whole product. A teammate opens
an invite link, the Coach says "start with the backend verification" and they discover
it was finished yesterday. Everything else the app claims about shared context dies
right there: it plainly did not read the state it says it reads.

The seeded challenge already has two closed nodes, so the check is no longer vacuous:
Dana joins cold and asks what to pick up, and the reply must not hand her one of them.

HOW "OFFERED" IS JUDGED. Mentioning a finished node is fine and often right -- "the
backend is already verified, so..." is context. What is not fine is leading with one.
So the test is on the FIRST node title the reply names: that node must not be done. It
must also name at least one live node, or the answer is not an answer.

    python scripts\\check_handoff.py
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

PORT = 8150

#: Cold, and deliberately open. A teammate who names a node has already done the work
#: this is testing.
DANA_ASKS = "I've just joined this. What should I pick up?"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def main() -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    cid = seed()
    nodes = [n for n in store.list_nodes(cid) if n.get("status") != "superseded"]
    done = {n["title"]: n for n in nodes if n.get("status") == "done"}
    live = {n["title"]: n for n in nodes if n.get("status") != "done"}

    _p(f"\nalready done : {sorted(done)}")
    _p(f"still open   : {len(live)} nodes")
    if not done:
        sys.exit("FAIL: the seed closed nothing, so this check would be vacuous again")

    threading.Thread(target=serve, daemon=True).start()
    time.sleep(3.0)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # A fresh context: Dana's own localStorage, her own user id, exactly as an
        # invite link arrives. A second tab would share Derek's identity.
        ctx = browser.new_context(viewport={"width": 1500, "height": 940})
        ctx.add_init_script("localStorage.setItem('ca_user','dana');"
                            "localStorage.setItem('ca_group','grp_dana');")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1200)

        _p(f"\ndana asks    : {DANA_ASKS}")
        page.fill("#input", DANA_ASKS)
        page.click("#send")
        page.wait_for_function("() => !document.getElementById('send').disabled",
                               timeout=300_000)
        page.wait_for_timeout(1000)

        bots = page.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        calls = page.eval_on_selector_all(
            ".msg.act", "els => els.map(e => e.innerText.trim())")
        page.screenshot(path=str(ROOT / "_handoff.png"))
        browser.close()

    reply = bots[-1] if bots else ""
    _p(f"\ntool calls   : {' | '.join(calls[-6:])}")
    _p(f"\nreply        : {reply[:700]}")

    # Where does each node title first appear in the reply?
    at = {}
    for title in list(done) + list(live):
        i = reply.lower().find(title.lower())
        if i >= 0:
            at[title] = i
    named = sorted(at, key=at.get)
    _p(f"\nnodes named  : {named}")

    failures: list[str] = []
    if not bots or len(reply) < 40:
        failures.append("the Coach did not answer a joining teammate at all")
    if not named:
        failures.append("the reply names no node from the graph -- it is not an answer, "
                        "and a teammate has no idea what to do next")
    else:
        first = named[0]
        _p(f"leads with   : {first!r} ({'DONE' if first in done else 'open'})")
        if first in done:
            failures.append(
                f"the Coach led a joining teammate with {first!r}, which was finished "
                "before she arrived -- the clearest possible sign it did not read the "
                "state it claims to read"
            )
        if not any(t in live for t in named):
            failures.append("the reply names only finished nodes, so there is nothing "
                            "for the teammate to actually start")

    # She should also arrive knowing what the party knows. That is the other half of
    # the promise, and it is cheap to check here.
    facts = (store.get("groups", "grp_team") or {}).get("shared_facts", [])
    inherited = [f for f in facts
                 if any(w in reply.lower() for w in f.lower().split()[:4])]
    _p(f"inherited    : {len(inherited)} of {len(facts)} party facts surfaced")

    if errors:
        failures.append(f"console errors: {errors}")

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    _p("\na joining teammate is handed live work, not finished work. wrote _handoff.png")


if __name__ == "__main__":
    main()
