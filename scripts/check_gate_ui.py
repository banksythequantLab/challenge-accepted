"""What a stranger sees when they open the app: the door, and nothing behind it.

check_auth_live.py proves the server refuses people. This proves the BROWSER does the
right thing when it is refused -- which is a different failure. A page that renders the
app, fires a poll, gets a 401 and paints the offline dot is technically secure and
looks completely broken, and that is the first screen a judge sees.

    python scripts\\check_gate_ui.py https://challengeaccepted.app
"""

from __future__ import annotations

import sys

DEFAULT_URL = "https://challengeaccepted.app"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL).rstrip("/")
    from playwright.sync_api import sync_playwright

    bad: list[str] = []
    errors: list[str] = []
    denied: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("response", lambda r: denied.append(f"{r.status} {r.request.method} "
                                                    f"{r.url.split(base)[-1][:70]}")
                if r.status in (401, 403) else None)

        page.goto(f"{base}/app", wait_until="networkidle", timeout=90000)
        # Long enough for the Firebase SDK to load off the CDN and for a poll cycle to
        # have fired if the gate were not holding it back.
        page.wait_for_timeout(9000)

        gate_up = page.is_visible("#gate")
        btn = page.is_visible("#gate-in")
        label = page.eval_on_selector("#gate-in", "e => e.textContent.trim()") if btn else ""
        _p(f"sign-in gate : {'shown' if gate_up else 'MISSING'}")
        _p(f"button       : {label or '(none)'}")

        if not gate_up:
            bad.append("the sign-in gate did not appear -- the app rendered open, or "
                       "the Firebase SDK failed to load and the page fell through")
        if not btn:
            bad.append("no sign-in button: there is a wall with no door")

        # A gate that lets the app poll behind it is not holding anything back.
        if denied:
            bad.append(f"the page made {len(denied)} request(s) that were refused "
                       f"before anyone signed in: {denied[:4]}")
        _p(f"refused calls: {len(denied)}")

        # `live` must not read offline: nothing is wrong with the server.
        live = page.eval_on_selector("#live", "e => e.title")
        _p(f"status dot   : {live}")
        if "Cannot reach" in (live or ""):
            bad.append("the status dot says the server is unreachable, on a healthy "
                       "server that is simply asking you to sign in")

        page.screenshot(path="_walk/gate.png")

        real = [e for e in errors if "gstatic" not in e]
        if real:
            bad.append(f"browser errors on the sign-in screen: {real[:3]}")
        _p(f"page errors  : {len(real)}")

        browser.close()

    if bad:
        _p("\n--- problems ---")
        for x in bad:
            _p(" * " + x)
        return 1
    _p("\nPASS -- a stranger gets a door, not a broken app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
