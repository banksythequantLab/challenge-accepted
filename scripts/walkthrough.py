"""Drive the DEPLOYED site in a real browser, cold, and photograph what breaks.

There is a hole in this folder that took a user saying "it isn't baked" to notice.
Every browser check boots a local server. Every production check speaks HTTP and never
opens a page. So the one combination a human actually uses -- a real browser against the
deployed service -- has never been exercised by anything.

That is the same shape as the FORGE outage: two green columns with the gap between them
untested. This closes it. No assertions, because the point is to see rather than to
confirm; it screenshots every beat, records how long each made the user wait, and prints
every console error, page error and failed request as they happen.

    python scripts\\walkthrough.py https://challengeaccepted.app

Writes _walk/NN_*.png (gitignored). Exits 1 only if the browser reported an error or a beat timed out.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "https://challengeaccepted.app"

#: Answers broad enough to fit whatever the Interviewer actually asks. The first
#: version was a fixed script, so when the agent asked about race day the reply was
#: about training evenings -- the transcript reads like two people talking past each
#: other, and the interview never converged. A canned script tests the script.
TURNS = [
    "I want to run a 10k in under 55 minutes by Christmas.",
    "I run about 3k twice a week at a slow pace, I have never trained properly, "
    "nothing has stopped me before, and I have no injuries.",
    "I can train four evenings a week for about 45 minutes. It is an official "
    "organised park 10k on Christmas Eve, and I am doing it alone.",
    "That's everything I know -- please accept the challenge, draw the map and build "
    "the tools.",
]

TURN_TIMEOUT_MS = 300000


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main(base: str) -> int:
    from playwright.sync_api import sync_playwright

    base = base.rstrip("/")
    marks, problems, n = [], [], [0]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # Everything the browser complains about, not just what we thought to assert.
        page.on("console", lambda m: problems.append(f"console {m.type}: {m.text}")
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: problems.append(
            f"requestfailed: {r.method} {r.url[:110]} -- {r.failure}"))
        page.on("response", lambda r: problems.append(
            f"HTTP {r.status}: {r.request.method} {r.url[:110]}") if r.status >= 400 else None)

        def shot(name):
            n[0] += 1
            # Keep the run's output out of the repo root -- these are scratch, not source.
            out = ROOT / "_walk"
            out.mkdir(exist_ok=True)
            path = out / f"{n[0]:02d}_{name}.png"
            page.screenshot(path=str(path))
            return path.name

        t0 = time.perf_counter()
        page.goto(f"{base}/app", wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(2500)
        marks.append(("cold open", time.perf_counter() - t0, shot("cold")))
        _p(f"cold open: {marks[-1][1]:.1f}s")

        for i, text in enumerate(TURNS, 1):
            t = time.perf_counter()
            page.fill("#input", text)
            page.click("#send")
            # Waiting for "a new bot bubble" was wrong: tool-call chips are bot bubbles
            # too, so the first `write_journal` chip ended the wait while the agents were
            # still working. That is how this script reported `nodes: 0` on a run that
            # had simply not finished -- measuring a turn before it ends and calling the
            # result a product failure. Wait for the app's OWN busy signal to clear.
            try:
                page.wait_for_function(
                    "() => !document.body.innerText.includes('WORKING')",
                    timeout=TURN_TIMEOUT_MS)
            except Exception:
                problems.append(f"turn {i} was still WORKING after "
                                f"{TURN_TIMEOUT_MS // 1000}s -- the user is left "
                                f"staring at a spinner")
            page.wait_for_timeout(1200)
            marks.append((f"turn {i}", time.perf_counter() - t, shot(f"turn{i}")))
            _p(f"turn {i}: {marks[-1][1]:.1f}s")

        # Let anything still running finish, then look at every panel a user can reach.
        page.wait_for_timeout(20000)
        shot("settled")

        for tab, label in (("quest", "quest"), ("journal", "journal"),
                           ("facts", "party"), ("chat", "chat")):
            try:
                page.click(f'.tab[data-p="{tab}"]')
                page.wait_for_timeout(900)
                shot(label)
            except Exception as exc:
                problems.append(f"could not open the {label} tab: {exc}")

        # The money shot: does a built tool actually open?
        try:
            page.click('.tab[data-p="quest"]')
            page.wait_for_timeout(700)
            if page.is_visible("[data-open]"):
                page.locator("[data-open]").first.click()
                page.wait_for_selector("#modal.on", timeout=15000)
                page.wait_for_timeout(2500)
                shot("tool")
                page.click("#m-close")
            else:
                problems.append("no 'Open tool' button anywhere -- FORGE produced "
                                "nothing the user can actually use")
        except Exception as exc:
            problems.append(f"opening a tool failed: {exc}")

        title = page.eval_on_selector("#title", "e => e.textContent.trim()")
        nodes = page.eval_on_selector_all(".node", "e => e.length")
        tools = page.eval_on_selector_all("[data-open]", "e => e.length")
        browser.close()

    _p(f"\ntitle : {title}")
    _p(f"nodes : {nodes}   tools openable: {tools}")
    _p(f"\n{'beat':<12} {'seconds':>9}   screenshot")
    for name, secs, f in marks:
        _p(f"{name:<12} {secs:>9.1f}   {f}")

    seen = list(dict.fromkeys(problems))
    _p(f"\n--- what the browser reported ({len(seen)} distinct) ---")
    for line in seen[:30] or ["nothing"]:
        _p(" * " + line)
    return 1 if seen else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
