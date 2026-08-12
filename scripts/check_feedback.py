"""The feedback loop, end to end: click thumbs-down, and prove it changes something.

The demo says "when something isn't useful I say so, and the next generation is
different." That was not true. The button wrote a Firestore row and NOTHING read it --
`record_feedback` had no reader anywhere in the codebase, `read_challenge_state` did
not return it, and no prompt mentioned it. The next generation was identical.

It also could not have been caught by a browser check, because the reason box was a
native `window.prompt()`, which blocks the page and every automation driving it.

So this checks both halves:

  1. THE UI HALF -- clicking thumbs-down opens an inline reason field (no native
     dialog), sending it stores the verdict AND the reason, and the button confirms.
  2. THE LOOP HALF -- the rejection comes back out of `read_challenge_state` resolved
     to a node and a tool name, and lands in the Quartermaster's actual prompt with
     the user's own words in it.

Half 2 is asserted against the real prompt string rather than a live model call: what
is being tested is whether the objection REACHES the model at all, which is exactly
where it was being dropped. What the model then does with it is a prompt-quality
question, not a wiring one.

    python scripts\\check_feedback.py
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
from challenge_accepted.services.store import store  # noqa: E402
from challenge_accepted.services.tools import _tool_feedback  # noqa: E402
from challenge_accepted.sub_agents.forge import quartermaster_instruction  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8143
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

#: Deliberately a specific, actionable complaint. "It was bad" would prove nothing --
#: the whole claim is that the user's OWN WORDS steer the rebuild.
REASON = "Too generic. I need the actual node names from my graph, not placeholders."

app = FastAPI()
app.include_router(router)


@app.get("/app")
def dashboard() -> FileResponse:
    return FileResponse(STATIC)


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


class FakeCtx:
    def __init__(self, **state):
        self.state = dict(state)


def main() -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    cid = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    failures: list[str] = []
    dialogs: list[str] = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 940})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        # A native prompt() would hang the run. Record it and dismiss, so the failure
        # is a clear message rather than a timeout nobody can read.
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))

        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1200)

        # Pick the quest that actually has a tool on it.
        page.evaluate("""() => {
          const n = [...document.querySelectorAll('.node')]
            .find(e => e.querySelector('circle')) || document.querySelector('.node');
          n.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        }""")
        page.wait_for_selector('[data-fb="down"]', timeout=5000)
        tool_name = page.inner_text(".tool div:nth-child(2)").strip()
        _p(f"rejecting    : {tool_name}")

        page.click('[data-fb="down"]')
        page.wait_for_timeout(300)

        if dialogs:
            browser.close()
            sys.exit(
                "FAIL: clicking thumbs-down opened a native dialog "
                f"({dialogs[0]!r}). That blocks the page and cannot be demoed."
            )

        if not page.is_visible("#whytext"):
            browser.close()
            sys.exit("FAIL: no inline reason field appeared after thumbs-down")

        # A field you cannot see or type into is the same as no field. `flex:1` inside
        # a narrow sidebar column is exactly the kind of thing that collapses.
        box = page.eval_on_selector("#whytext", "e => e.getBoundingClientRect().width")
        _p(f"reason field : {box:.0f}px wide")
        if box < 150:
            failures.append(f"reason field collapsed to {box:.0f}px -- unusable")

        page.fill("#whytext", REASON)
        page.click("#whysend")
        page.wait_for_selector(".why.done", timeout=5000)
        confirm = page.inner_text(".why.done").strip()
        _p(f"confirmation : {confirm}")

        still_enabled = page.eval_on_selector_all(
            "[data-fb]", "els => els.filter(e => !e.disabled).length")
        page.screenshot(path=str(ROOT / "_feedback.png"))

        # --- the rebuild button -------------------------------------------------
        # Telling the user "now go and ask for a rebuild" is asking them to do the
        # product's job. Clicking it must switch to the chat and compose a turn that
        # names the step, the tool and their objection -- Warden reads the chat, and
        # "rebuild it" alone leaves it guessing which node we mean.
        if not page.is_visible("#rebuild"):
            browser.close()
            sys.exit("FAIL: no Rebuild button after a thumbs-down")

        # Do not actually run the turn -- that costs a model call and is drive_chat's
        # job. Neuter send() and assert on what it was about to send.
        page.evaluate("() => { window.__sent = null; window.send = "
                      "() => { window.__sent = document.getElementById('input').value; }; }")
        page.click("#rebuild")
        page.wait_for_timeout(300)
        sent = page.evaluate("() => window.__sent")
        on_chat = page.eval_on_selector(
            '.tab[data-p="chat"]', "e => e.classList.contains('on')")
        _p(f"\nrebuild sends: {(sent or '')[:150]!r}")
        _p(f"switched tab : {on_chat}")
        browser.close()

    if still_enabled:
        failures.append(f"{still_enabled} feedback button(s) still clickable after voting")
    if not confirm:
        failures.append("no confirmation text after sending")
    if not sent:
        failures.append("Rebuild did not start a turn")
    else:
        if REASON not in sent:
            failures.append("the rebuild turn does not carry the user's reason")
        if tool_name not in sent:
            failures.append(f"the rebuild turn does not name the tool ({tool_name})")
        if "reworded" not in sent.lower():
            failures.append("the rebuild turn does not rule out a reworded repeat")
    if not on_chat:
        failures.append("Rebuild left the user on the Quest tab, watching nothing happen")

    # --- half 1: it was actually stored, with the reason -----------------------
    stored = store.list_feedback(cid)
    mine = [f for f in stored if f.get("reason") == REASON]
    _p(f"\nstored rows  : {len(stored)}  (matching my reason: {len(mine)})")
    if not mine:
        failures.append("the reason never reached the store")
    elif mine[0].get("verdict") != "down":
        failures.append(f"verdict stored as {mine[0].get('verdict')!r}, expected 'down'")

    # --- half 2: it comes back out, resolved and usable ------------------------
    resolved = [f for f in _tool_feedback(cid) if f.get("verdict") == "down"]
    _p(f"read back    : {resolved[:1]}")
    if not resolved:
        failures.append("read_challenge_state does not surface the rejection")
    else:
        r = resolved[0]
        if not r.get("tool_name"):
            failures.append("rejection came back without a tool name -- a bare tool_ id "
                            "is useless to a model")
        if not r.get("node_id"):
            failures.append("rejection came back without a node_id")

    # --- half 2b: it reaches the agent that has to act on it -------------------
    before = quartermaster_instruction(FakeCtx())
    after = quartermaster_instruction(FakeCtx(challenge_id=cid))
    _p(f"\nprompt grew  : {len(before)} -> {len(after)} chars")
    if REASON not in after:
        failures.append("the user's own words never reach the Quartermaster prompt")
    if tool_name and tool_name not in after:
        failures.append(f"the rejected tool {tool_name!r} is not named in the prompt")
    if "REJECTED SO FAR" not in after:
        failures.append("the rejection banner did not fire")
    if before == after:
        failures.append("Quartermaster's prompt is identical with and without feedback "
                        "-- the loop is still open")

    _p(f"\nconsole errors : {errors if errors else 'none'}")
    _p(f"native dialogs : {dialogs if dialogs else 'none'}")

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    _p("\nthumbs-down is wired all the way to the agent that rebuilds. wrote _feedback.png")


if __name__ == "__main__":
    main()
