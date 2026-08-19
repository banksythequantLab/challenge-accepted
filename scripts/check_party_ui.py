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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_URL = "https://challengeaccepted.app"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def open_as(browser, base: str, user: str, url: str):
    """A browser that has never seen this app, wearing a specific identity.

    A second browser CONTEXT is a second person: separate cookies, separate storage,
    separate Firebase session. Two tabs would share one sign-in and quietly test
    nothing.

    Since auth landed, the identity is a real Google-verified uid rather than a
    localStorage string, so the seeding below only matters against an unauthenticated
    local server. On production the page signs in and overwrites it.
    """
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        permissions=["clipboard-read", "clipboard-write"],
    )
    # Guarded, because `add_init_script` runs in EVERY frame in the context -- including
    # the sandboxed iframe a tool opens in, where touching localStorage throws
    # `lacks the 'allow-same-origin' flag`. Unguarded, this check reported its own
    # fixture as a page error in the product, on a tool whose source does not mention
    # storage at all. A test fixture that runs inside the thing under test has to be as
    # careful as the thing under test.
    ctx.add_init_script(f"""
        try {{
          localStorage.setItem('ca_user', {user!r});
          localStorage.setItem('ca_group', 'grp_' + {user!r});
        }} catch (e) {{}}
    """)
    page = ctx.new_page()
    page.goto(url, wait_until="networkidle", timeout=90000)
    if page.is_visible("#gate"):
        from testauth import sign_in
        user = sign_in(page, user)
    page.wait_for_timeout(3000)
    return ctx, page, user


def take_the_invite(page) -> bool:
    """Click 'Join this quest' if the app is offering it.

    This IS the membership model: holding the link gets you an invitation, not the
    data. Anyone arriving on a quest they have not joined sees this button, and a
    check that skipped it would be asserting against an empty screen.
    """
    btn = page.get_by_role("button", name="Join this quest")
    if not btn.count():
        return False
    btn.first.click()
    page.wait_for_timeout(2500)
    return True


def snapshot(page) -> dict:
    return {
        "title": page.eval_on_selector("#title", "e => e.textContent.trim()"),
        "nodes": page.eval_on_selector_all("#graph .node", "e => e.length"),
        "tools": int(page.eval_on_selector("#c-tools", "e => e.textContent.trim()")),
        "party": int(page.eval_on_selector("#c-party", "e => e.textContent.trim()")),
    }


def wait_for_dashboard(page, timeout_ms: int = 30000) -> bool:
    """Wait for the quest to actually arrive, rather than sleeping and hoping.

    `open_as` waits a fixed 3 seconds after sign-in. On a cold Cloud Run instance the
    dashboard has not landed by then, and a snapshot taken in that window reads
    `nodes: 0` and the empty-state title -- which this check then reported as "the
    owner cannot see the map of their own challenge", four times over, about a
    challenge whose map was fine.

    A fixed wait that is slightly too short does not fail; it lies. Wait for the
    thing.
    """
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#graph .node').length > 0"
            " || (document.getElementById('c-nodes')"
            "     && +document.getElementById('c-nodes').textContent > 0)",
            timeout=timeout_ms)
        return True
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        _p("usage: check_party_ui.py <challenge_id> --owner <uid> [base_url]")
        return 2
    args = sys.argv[1:]
    owner_uid = None
    if "--owner" in args:
        i = args.index("--owner")
        owner_uid = args[i + 1]
        del args[i:i + 2]
    cid = args[0]
    base = (args[1] if len(args) > 1 else DEFAULT_URL).rstrip("/")

    # `--owner` is required, and this check ran for a while without noticing that it
    # had become required. It was written when possession of `?id=<cid>` WAS access:
    # any identity could open the link and join. Rotatable invite keys ended that --
    # a link with no `&k=` is 403 now, by design, and that is the feature.
    #
    # So without --owner the "owner" here is a stranger who cannot get in, sees an
    # empty screen, and the check reports SIX product bugs that are all the same
    # fixture mistake: no map, no tools, no party, nothing learned. Every one of them
    # a lie about a working product.
    #
    # A check that has quietly outlived the design it was written against is worse
    # than no check. Refuse, and say which.
    if not owner_uid:
        _p("--owner <uid> is required. A bare ?id= link stopped being a way in when "
           "rotatable invite keys shipped, so without the real owner this check signs "
           "in as a stranger, sees an empty screen, and reports the product as broken "
           "in six different ways. Pass the uid that created the challenge.")
        return 2

    from playwright.sync_api import sync_playwright

    a_id = owner_uid or ("u_owner_" + uuid.uuid4().hex[:6])
    b_id = "u_mate_" + uuid.uuid4().hex[:6]
    bad: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # --- the owner ------------------------------------------------------------
        ctx_a, a, a_id = open_as(browser, base, a_id, f"{base}/app?id={cid}")
        a.on("pageerror", lambda e: bad.append(f"owner pageerror: {e}"))
        # Pass --owner <uid> to sign in as the account that actually created the
        # challenge; otherwise this identity joins like anyone else with the link.
        if take_the_invite(a):
            _p("owner  : joined via the invite (not the original creator)")
        wait_for_dashboard(a)
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
        ctx_b, b, b_id = open_as(browser, base, b_id, link or f"{base}/app?id={cid}")
        b.on("pageerror", lambda e: bad.append(f"teammate pageerror: {e}"))
        # The invite must lead somewhere. If no join is offered and no map appears,
        # the link is a dead end -- which is the failure this whole check exists for.
        before = snapshot(b)
        joined = take_the_invite(b)
        _p(f"mate   : {'joined via the invite button' if joined else 'already a member'}")
        if not joined and not before["nodes"]:
            bad.append("the invite link offered no way in and showed no map: "
                       "a teammate arrives at a dead end")
        wait_for_dashboard(b)
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
