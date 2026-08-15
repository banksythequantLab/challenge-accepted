"""Two people, two browsers, one quest -- the claim the Collaborative track judges.

Everything else in this repo proves the agents work. This proves the *shared* part:
that the Invite button produces a link which drops a second person into the SAME
challenge, that they see the map and tools the first person's agents built, and that
both screens agree on who is in the party.

It runs against a challenge that already exists, so it costs no model calls:

    python scripts\\check_party_ui.py chal_e171b48edd34
    python scripts\\check_party_ui.py chal_e171b48edd34 https://challengeaccepted.app

Exits non-zero on the first thing a real pair of users would notice.
"""

from __future__ import annotations

import sys
import uuid

DEFAULT_URL = "https://challengeaccepted.app"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def open_as(browser, base: str, user: str, url: str):
    """A browser that has never seen this app, wearing a specific identity.

    Identity today is a localStorage id, so a second *context* is a second person.
    Seeding it before any script runs is what stops both tabs being the same user.
    """
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        permissions=["clipboard-read", "clipboard-write"],
    )
    ctx.add_init_script(f"""
        localStorage.setItem('ca_user', {user!r});
        localStorage.setItem('ca_group', 'grp_' + {user!r});
    """)
    page = ctx.new_page()
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(3000)
    return ctx, page


def snapshot(page) -> dict:
    return {
        "title": page.eval_on_selector("#title", "e => e.textContent.trim()"),
        "nodes": page.eval_on_selector_all("#graph .node", "e => e.length"),
        "tools": int(page.eval_on_selector("#c-tools", "e => e.textContent.trim()")),
        "party": int(page.eval_on_selector("#c-party", "e => e.textContent.trim()")),
    }


def main() -> int:
    if len(sys.argv) < 2:
        _p("usage: check_party_ui.py <challenge_id> [base_url]")
        return 2
    cid = sys.argv[1]
    base = (sys.argv[2] if len(sys.argv) > 2 else DEFAULT_URL).rstrip("/")

    from playwright.sync_api import sync_playwright

    a_id = "u_owner_" + uuid.uuid4().hex[:6]
    b_id = "u_mate_" + uuid.uuid4().hex[:6]
    bad: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # --- the owner ------------------------------------------------------------
        ctx_a, a = open_as(browser, base, a_id, f"{base}/app?id={cid}")
        a.on("pageerror", lambda e: bad.append(f"owner pageerror: {e}"))
        sa = snapshot(a)
        _p(f"owner  : {sa}")
        if not sa["nodes"]:
            bad.append("the owner cannot see the map of their own challenge")

        # The Invite button is the whole feature. Take the link it actually copies,
        # not a link this script assembles -- assembling it would test nothing.
        # It lives in the Party pane, so a user has to be looking at Party to find it.
        a.click('.tab[data-p="facts"]')
        a.wait_for_timeout(500)
        a.click("#invite")
        a.wait_for_timeout(600)
        link = a.evaluate("() => navigator.clipboard.readText()")
        _p(f"invite : {link}")
        if not link or cid not in link:
            bad.append(f"Invite copied {link!r}, which does not carry the challenge id")

        # --- the teammate ---------------------------------------------------------
        ctx_b, b = open_as(browser, base, b_id, link or f"{base}/app?id={cid}")
        b.on("pageerror", lambda e: bad.append(f"teammate pageerror: {e}"))
        sb = snapshot(b)
        _p(f"mate   : {sb}")

        if sb["title"] != sa["title"]:
            bad.append(f"teammate sees a different quest: {sb['title']!r} "
                       f"vs {sa['title']!r}")
        if sb["nodes"] != sa["nodes"]:
            bad.append(f"teammate sees {sb['nodes']} nodes, owner sees {sa['nodes']}")
        if sb["tools"] != sa["tools"]:
            bad.append(f"teammate sees {sb['tools']} tools, owner sees {sa['tools']}")

        # A teammate who can see the map but not open the tools has not really joined.
        b.click('.tab[data-p="quest"]')
        b.wait_for_timeout(600)
        armed = b.evaluate("""() => [...document.querySelectorAll('#graph .node')]
            .filter(n => /,\\s*\\d+\\s+tools?\\b/.test(n.getAttribute('aria-label')||''))
            .map(n => n.dataset.id)""")
        if not armed:
            bad.append("no node offers a tool to the teammate")
        else:
            b.click(f'#graph .node[data-id="{armed[0]}"]')
            b.wait_for_timeout(700)
            if not b.locator("[data-open]").count():
                bad.append("teammate selected a node with a tool and got no Open button")
            else:
                b.locator("[data-open]").first.click()
                b.wait_for_selector("#modal.on", timeout=15000)
                body = b.eval_on_selector("#modal", "e => e.innerText")
                _p(f"mate opened a tool: {body.splitlines()[0][:70]}")
                if len(body) < 200:
                    bad.append("the tool opened for the teammate but rendered empty")
                b.click("#m-close")

        # --- does the roster agree? ------------------------------------------------
        # Both clients poll; give the join a couple of cycles to land on both screens.
        for _ in range(12):
            a.wait_for_timeout(1500)
            pa = int(a.eval_on_selector("#c-party", "e => e.textContent.trim()"))
            pb = int(b.eval_on_selector("#c-party", "e => e.textContent.trim()"))
            if pa >= 2 and pb >= 2:
                break
        _p(f"party  : owner sees {pa}, teammate sees {pb}")
        if pa < 2:
            bad.append(f"the owner's screen still says {pa} in party after a teammate "
                       f"joined -- the collaboration is invisible to the person who "
                       f"sent the invite")
        if pb < 2:
            bad.append(f"the teammate's screen says {pb} in party")

        # Leave both screenshots on the Party pane -- that is the pane this check is
        # about, and a screenshot of some other tab proves nothing about it.
        for page, name in ((a, "owner"), (b, "mate")):
            page.click('.tab[data-p="facts"]')
            page.wait_for_timeout(700)
            page.screenshot(path=f"_walk/party_{name}.png")
        shown = b.eval_on_selector_all("#facts li", "els => els.map(e => e.innerText)")
        _p(f"party notebook as the teammate sees it ({len(shown)}):")
        for f in shown:
            _p("  * " + f)
        if not shown or any("Nothing learned yet" in f for f in shown):
            bad.append("the teammate's Party pane says nothing has been learned, on a "
                       "challenge with a full map and built tools")
        ctx_a.close()
        ctx_b.close()
        browser.close()

    if bad:
        _p("\n--- problems ---")
        for x in dict.fromkeys(bad):
            _p(" * " + x)
        return 1
    _p("\nPASS -- an invite link puts a second person on the same quest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
