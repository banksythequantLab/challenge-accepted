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
sys.path.insert(0, str(Path(__file__).resolve().parent))
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

#: Measured, not guessed: the final turn of a real run (charter -> cartographer ->
#: quartermaster -> four Toolwrights building six tools) took 250s against production.
#: A 300s budget was one slow model call away from calling a healthy run a failure.
TURN_TIMEOUT_MS = 600000

#: Ids of map nodes that advertise at least one built tool, read off the accessible
#: name the app already writes ("Draft the plan. todo, 2 tools, ready to start").
ARMED_NODE_IDS = """() => [...document.querySelectorAll('#graph .node')]
  .filter(n => /,\\s*\\d+\\s+tools?\\b/.test(n.getAttribute('aria-label') || ''))
  .map(n => n.dataset.id)"""


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
        # Sign in if the deployment asks for it. A real Google popup cannot be
        # automated; this reaches the page's own Firebase instance instead, so
        # everything after this line is the app a signed-in person actually uses.
        if page.is_visible("#gate"):
            from testauth import sign_in
            who = sign_in(page)
            _p(f"signed in as {who}")
            shot("signed-in")
        page.wait_for_timeout(2500)
        marks.append(("cold open", time.perf_counter() - t0, shot("cold")))
        _p(f"cold open: {marks[-1][1]:.1f}s")

        for i, text in enumerate(TURNS, 1):
            t = time.perf_counter()
            page.fill("#input", text)
            page.click("#send")
            # Two wrong signals so far, both of which made a working product look broken:
            #   1. "a new bot bubble" -- tool-call chips are bot bubbles too, so the
            #      first `write_journal` chip ended the wait immediately.
            #   2. "the WORKING spinner is gone" -- app.html removes that placeholder the
            #      moment the response STARTS streaming, not when it ends. That is why
            #      this script reported turns of 3-9s and `nodes: 0`: it screenshotted a
            #      run that was still in flight and then blamed the product. The same
            #      conversation over raw HTTP takes minutes and saves 10 nodes.
            # #send is disabled for exactly as long as `busy` is true, and `busy` is
            # cleared in the stream's `finally`. That is the turn boundary.
            try:
                page.wait_for_function(
                    "() => document.getElementById('send').disabled", timeout=15000)
            except Exception:
                problems.append(f"turn {i}: Send never went busy -- the click may "
                                f"not have registered")
            try:
                page.wait_for_function(
                    "() => !document.getElementById('send').disabled",
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
        #
        # This asked `is_visible("[data-open]")` straight after clicking the Quest tab
        # and reported "FORGE produced nothing the user can actually use" on a run whose
        # header said 5 TOOLS FORGED. The Open-tool button lives in the detail pane,
        # which only renders once a NODE is selected -- so the check was asserting that
        # a panel it had never opened was empty. A tool that cannot be reached without
        # clicking a node is still reachable; the click is the product.
        try:
            page.click('.tab[data-p="quest"]')
            page.wait_for_timeout(700)
            # A node carrying a tool says so in its aria-label ("..., 2 tools, ...").
            # That is the accessible truth and the only stable hook -- the badge itself
            # is an unclassed <g>. Matched on the count, not the bare word, so a node
            # called "Build tooling" is not mistaken for one that has a tool.
            armed_ids = page.evaluate(ARMED_NODE_IDS)
            target = (page.locator(f'#graph .node[data-id="{armed_ids[0]}"]')
                      if armed_ids else page.locator("#graph .node").first)
            if not page.locator("#graph .node").count():
                problems.append("the quest map has no nodes at all")
            else:
                target.click()
                page.wait_for_timeout(900)
                if page.locator("[data-open]").count():
                    page.locator("[data-open]").first.click()
                    page.wait_for_selector("#modal.on", timeout=15000)
                    page.wait_for_timeout(2500)
                    shot("tool")
                    page.click("#m-close")
                else:
                    problems.append("selected a node and it offered no tool to open -- "
                                    "FORGE produced nothing the user can reach")
        except Exception as exc:
            problems.append(f"opening a tool failed: {exc}")

        title = page.eval_on_selector("#title", "e => e.textContent.trim()")
        nodes = page.eval_on_selector_all(".node", "e => e.length")
        # Count nodes that ADVERTISE a tool, not [data-open] buttons: the detail pane
        # renders one node at a time, so counting buttons counts the selection.
        tools = len(page.evaluate(ARMED_NODE_IDS))
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
