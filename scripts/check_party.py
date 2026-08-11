"""Two real browsers, one quest: proof the collaborative beat works in the UI.

The demo claims that what one teammate learns reaches the others. Until now that was
only ever proven by a test that handed both users the same group_id, which the real
client never does -- it mints `grp_<user_id>` into localStorage on first visit, so a
teammate opening an invite link arrives insisting they are a party of one.

This drives the actual product surface:

  Derek   opens /app?id=<cid>                    -> party of 1
  Dana    opens the SAME link in a fresh context -> her own user id, her own localStorage
  Dana    tells the agents something new
  Derek   refreshes                              -> party of 2, and Dana's discovery
                                                    is sitting in his Party Knowledge

Two separate browser CONTEXTS, not two tabs: tabs share localStorage and would let a
broken build pass.

    python scripts\\check_party.py                 # boots main.py locally
    python scripts\\check_party.py https://...run.app   # drives a deployment
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

from main import app  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8141

#: Phrased the way a teammate actually would, and deliberately a fact rather than a
#: question -- the point is that the agents file it for the party, not answer it.
#:
#: It must also be ABOUT the seeded challenge. The first version had Dana announce a
#: park permit rule on a hackathon quest, and Warden quite reasonably treated a total
#: non-sequitur as a new goal and sent her to the Interviewer. That was the probe being
#: wrong, not the product -- but it hid a real bug underneath, so: keep it on topic.
DANA_SAYS = (
    "Heads up for the team before I forget: I read the Devpost rules and the GitHub "
    "repo has to be public at submission time -- sharing it with the judges is not "
    "enough. Make sure everyone working on this knows."
)

#: Content words we expect to survive whatever paraphrase the agent files it under.
EXPECT_WORDS = ("public", "repo")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _pin_identity(context, user_id: str) -> None:
    """Force a known user id before any app script runs.

    The app reads localStorage at parse time, so this has to be an init script -- set
    it after navigation and you are testing the second page load, not the first.
    """
    context.add_init_script(
        f"localStorage.setItem('ca_user', {user_id!r});"
        f"localStorage.setItem('ca_group', 'grp_{user_id}');"
    )


def _party_count(page) -> int:
    return int(page.inner_text("#c-party").strip() or 0)


def _facts(page) -> list[str]:
    return page.eval_on_selector_all("#facts li", "els => els.map(e => e.innerText.trim())")


def main() -> None:
    remote = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else None
    base = remote or f"http://127.0.0.1:{PORT}"

    if remote:
        sys.exit(
            "FAIL: this check seeds a challenge into the local store, so it cannot "
            "drive a deployment. Run it without a URL."
        )

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    cid = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(3.0)
    url = f"{base}/app?id={cid}"
    _p(f"\ndriving {url}")

    from playwright.sync_api import sync_playwright

    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        derek_ctx = browser.new_context(viewport={"width": 1500, "height": 940})
        dana_ctx = browser.new_context(viewport={"width": 1500, "height": 940})
        _pin_identity(derek_ctx, "derek")
        _pin_identity(dana_ctx, "dana")

        derek = derek_ctx.new_page()
        dana = dana_ctx.new_page()
        for pg in (derek, dana):
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(str(e)))

        derek.goto(url, wait_until="networkidle")
        derek.click('.tab[data-p="facts"]')
        derek.wait_for_timeout(800)
        before_count = _party_count(derek)
        before_facts = _facts(derek)
        _p(f"derek before : party={before_count} facts={len(before_facts)}")

        # The invite link is the only sanctioned way in, so test the one the button
        # actually produces rather than a URL we assembled ourselves.
        derek_ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        derek.click("#invite")
        derek.wait_for_timeout(400)
        invite = derek.evaluate("() => navigator.clipboard.readText()")
        _p(f"invite link  : {invite}")
        if not invite or f"id={cid}" not in invite:
            browser.close()
            sys.exit(f"FAIL: Invite copied {invite!r}, which does not point at {cid}")

        dana.goto(invite, wait_until="networkidle")
        dana.wait_for_timeout(800)
        dana_sees_first = _facts_after_tab(dana)
        _p(f"dana on join : sees {len(dana_sees_first)} inherited fact(s)")
        for f in dana_sees_first:
            _p("   - " + f[:110])

        _p(f"\ndana says    : {DANA_SAYS[:80]}...")
        dana.click('.tab[data-p="chat"]')
        dana.fill("#input", DANA_SAYS)
        dana.click("#send")
        dana.wait_for_function(
            "() => !document.getElementById('send').disabled", timeout=300_000)
        dana.wait_for_timeout(1500)
        reply = dana.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        _p("dana got back: " + (reply[-1][:200].replace("\n", " ") if reply else "(nothing)"))
        # What the agents actually DID, as opposed to what they said they did. When
        # Warden claimed to have saved a fact it did not save, this line is what told
        # the difference between "the tool never fired" and "the tool fired and the
        # write was dropped".
        acts = dana.eval_on_selector_all(
            ".msg.act", "els => els.map(e => e.innerText.trim())")
        _p("dana tool calls: " + (" | ".join(acts) if acts else "(none)"))
        # The session state the SERVER holds for Dana. If challenge_id is missing here,
        # every downstream symptom follows: _group_id falls back to her private group,
        # warden_instruction never sees an in-flight challenge, and read_challenge_state
        # comes back empty -- which is exactly what happened.
        dana_state = dana.evaluate(
            """async () => {
                 const u = localStorage.getItem('ca_user');
                 const r = await fetch(`/apps/challenge_accepted/users/${u}/sessions`);
                 if (!r.ok) return 'could not list sessions: ' + r.status;
                 const list = await r.json();
                 const rows = Array.isArray(list) ? list : (list.sessions || []);
                 return rows.map(s => s.state);
               }""")

        # Derek never touched his browser. The 4s poll should bring it to him.
        derek.wait_for_timeout(6000)
        after_count = _party_count(derek)
        after_facts = _facts(derek)
        _p(f"\nderek after  : party={after_count} facts={len(after_facts)}")
        for f in after_facts:
            _p("   - " + f[:110])
        roster = derek.inner_text("#roster").strip()
        _p(f"derek roster : {roster}")

        derek.screenshot(path=str(ROOT / "_party_derek.png"))
        dana.screenshot(path=str(ROOT / "_party_dana.png"))
        browser.close()

    _p(f"\nconsole errors : {errors if errors else 'none'}")

    # We are in the same process as the server, so we can look past the UI at what was
    # really written. This separates "the UI did not render it" from "it was never
    # stored", which are two very different bugs.
    from challenge_accepted.services.store import store as _store
    stored = (_store.get("groups", "grp_team") or {}).get("shared_facts", [])
    _p(f"store grp_team : {len(stored)} fact(s)")
    for f in stored:
        _p("   . " + f[:110])
    stray = (_store.get("groups", "grp_dana") or {}).get("shared_facts", [])
    _p(f"store grp_dana : {len(stray)} fact(s)  <- anything here is a leak")
    for f in stray:
        _p("   . " + f[:110])
    _p(f"dana session   : {dana_state}")

    fresh = [f for f in after_facts if f not in before_facts]
    landed = [f for f in fresh if all(w in f.lower() for w in EXPECT_WORDS)]

    _p("\n--- verdict ---")
    _p(f"dana inherited the party's facts   : {len(dana_sees_first) >= len(before_facts)}")
    _p(f"party count rose {before_count} -> {after_count}          : {after_count > before_count}")
    _p(f"dana's discovery reached derek     : {bool(landed)}")

    if len(dana_sees_first) < len(before_facts):
        sys.exit("FAIL: Dana joined and saw fewer facts than the party already had")
    if after_count <= before_count:
        sys.exit(f"FAIL: party count stayed at {after_count}; Dana never joined the roster")
    if "dana" not in roster.lower():
        sys.exit(f"FAIL: roster does not name Dana: {roster!r}")
    if not landed:
        sys.exit(
            "FAIL: nothing matching "
            f"{EXPECT_WORDS} reached Derek's Party Knowledge. New facts were: {fresh}"
        )

    _p("\nthe collaborative beat works in the UI. wrote _party_derek.png, _party_dana.png")


def _facts_after_tab(page) -> list[str]:
    page.click('.tab[data-p="facts"]')
    page.wait_for_timeout(600)
    return _facts(page)


if __name__ == "__main__":
    main()
