"""The leave/remove controls, in a real browser, on the deployed site.

`check_party_exit_live.py` proves the API enforces the rules. That is not the same
claim as "a person can do this": the control I wrote could be rendering for the wrong
person, or wired to nothing, and every API assertion would still pass. Shipping a
permission model with an untested button is how you end up with a Leave that does
nothing and a repo that says leaving works.

What it drives, as two separate browser contexts -- two people, not two tabs:

  1. the OWNER sees a Remove button naming each teammate, and no Leave for themselves;
  2. the TEAMMATE sees Leave and no Remove -- the client must not offer a control the
     server will refuse, because a 403 the user cannot avoid reads as a broken app;
  3. the button is two-click armed: one click says "Sure?", the second acts. There is
     no confirm() anywhere near this, deliberately -- a native modal blocks the page
     and this check would hang on the one control that destroys access;
  4. after leaving, the teammate's page no longer holds the quest, and the owner's
     roster drops back on its own poll.

    python scripts\\check_party_exit_ui.py <challenge_id> --owner <uid>

Costs no model calls.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_party_ui import DEFAULT_URL, _p, open_as  # noqa: E402


def exits(page) -> list[str]:
    page.click("[data-p='facts']")
    page.wait_for_timeout(400)
    return [b.inner_text().strip()
            for b in page.locator("#party-exits button.rm").all()]


def main() -> int:
    args = list(sys.argv[1:])
    base = args.pop(0).rstrip("/") if args and args[0].startswith("http") else DEFAULT_URL
    owner = args[args.index("--owner") + 1] if "--owner" in args else None
    args = [a for a in args if a != owner and not a.startswith("--")]
    if not args or not owner:
        _p("usage: check_party_exit_ui.py <challenge_id> --owner <uid>")
        return 2
    cid = args[0]

    from testauth import PREFIX, mint

    mate = PREFIX + "ui_" + uuid.uuid4().hex[:6]
    url = f"{base}/app?id={cid}"
    bad: list[str] = []

    # Put the teammate on the roster through the API rather than the UI. Joining is
    # already proven elsewhere; mixing it in here would mean a failure could be either
    # bug and the check could not say which.
    requests.post(f"{base}/api/challenges/{cid}/join",
                  headers={"Authorization": "Bearer " + mint(mate)},
                  json={"user_id": mate}, timeout=60)
    _p(f"target : {url}\nowner  : {owner}\nmate   : {mate}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            o_ctx, o_page, _ = open_as(browser, base, owner, url)
            m_ctx, m_page, _ = open_as(browser, base, mate, url)

            o_buttons, m_buttons = exits(o_page), exits(m_page)
            _p(f"owner sees   : {o_buttons}")
            _p(f"teammate sees: {m_buttons}")

            if not any(b.startswith("Remove") for b in o_buttons):
                bad.append("the owner has no Remove control -- the party is still "
                           "append-only from the only screen anyone uses")
            if any(b.startswith("Leave") for b in o_buttons):
                bad.append("the owner is offered Leave, and the server returns 409 for "
                           "that -- a control whose only outcome is an error")
            if m_buttons != ["Leave this quest"]:
                bad.append(f"the teammate should see exactly one Leave control, got "
                           f"{m_buttons}")

            if m_buttons:
                _p("\nclicking Leave once (must ARM, not act):")
                btn = m_page.locator("#party-exits button.rm").first
                btn.click()
                m_page.wait_for_timeout(300)
                armed = btn.inner_text().strip()
                _p(f"  button now reads: {armed!r}")
                if armed != "Sure?":
                    bad.append(f"one click did not arm the button -- it read {armed!r}. "
                               "A single click on a control that revokes your own "
                               "access is a mis-click waiting to happen")
                still = requests.get(f"{base}/api/challenges/{cid}/dashboard",
                                     headers={"Authorization": "Bearer " + mint(mate)},
                                     timeout=60)
                _p(f"  access after ONE click: {still.status_code} (must be 200)")
                if still.status_code != 200:
                    bad.append("one click already removed them; arming is decorative")

                _p("\nclicking again (must act):")
                btn.click()
                m_page.wait_for_timeout(4000)
                gone = requests.get(f"{base}/api/challenges/{cid}/dashboard",
                                    headers={"Authorization": "Bearer " + mint(mate)},
                                    timeout=60)
                _p(f"  access after TWO clicks: {gone.status_code} (must be 403)")
                if gone.status_code != 403:
                    bad.append("the second click did not actually remove them -- the "
                               "button looks like it worked and did nothing")
                _p(f"  their page url : {m_page.url}")
                if f"id={cid}" in m_page.url:
                    bad.append("their page still points at the quest, so a reload "
                               "drops them straight into a 403")

                # The owner is a different browser that nobody touched. Their roster
                # must catch up on its own poll -- that is the collaborative claim.
                o_page.wait_for_timeout(6000)
                after = exits(o_page)
                _p(f"\nowner's controls after the poll: {after}")
                if any(mate[:12] in b or "Ui " in b for b in after):
                    bad.append("the owner still sees a Remove for someone who left")
        finally:
            requests.delete(f"{base}/api/challenges/{cid}/party/{mate}",
                            headers={"Authorization": "Bearer " + mint(owner)},
                            timeout=60)
            browser.close()

    if bad:
        _p("\n--- problems ---")
        for b in bad:
            _p("  * " + b)
        return 1
    _p("\nPASS: the control is there for the right person and it does what it says.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
