"""Does a shared tool LOOK shared, and does a clobber get stopped in a real browser?

`check_shared_tool_live.py` proves the endpoint: one record for the party, 409 on a
stale save. That is not the claim either. The claim is that a person opening a shared
ledger can tell it is shared, and that when a teammate saves underneath them they are
told so and shown the winning copy -- rather than watching their own number vanish on
the next reload with no explanation.

Between the endpoint and that sentence sit things no unit test touches: a badge that
has to be cleared when you open a different tool, a debounced save that carries the
version it read, a 409 that arrives as a rejected promise inside a `catch`, and a
re-render that has to reseed the sandboxed iframe.

So this drives it:

  1. Derek opens a shared tool. The header says shared, and names nobody yet.
  2. Dana saves over HTTP while his modal is open. He does not know.
  3. Derek writes from inside the frame, the way a tool does.
  4. His save is refused. He is TOLD, by name, and the tool reloads showing hers.
  5. He opens a personal tool: no shared badge left over from the last one.

    python scripts\\check_shared_tool_ui.py [url]

Seeds its own challenge and deletes it. Costs no model calls.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_party_ui import DEFAULT_URL, _p, open_as  # noqa: E402

#: A tool that writes through `localStorage`, which the dashboard's shim turns into a
#: postMessage back to the parent. Deliberately minimal: this check is about the
#: brokering, and a tool with its own logic would put that logic in the blast radius.
LEDGER = """<!doctype html><meta charset="utf-8"><body>
<p>Total: <b id="out" data-smoke>0</b></p>
<script>
  document.getElementById('out').textContent = localStorage.getItem('total') || '0';
  window.setTotal = function (v) { localStorage.setItem('total', v); };
</script>
</body>"""


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL).rstrip("/")
    from testauth import PREFIX, mint

    from challenge_accepted.services.store import store

    health = requests.get(f"{base}/api/healthz", timeout=60).json()
    _p(f"target : {base}")
    _p(f"health : store={health.get('store')} auth={health.get('auth')}")

    tag = uuid.uuid4().hex[:6]
    derek = PREFIX + "shui_derek_" + tag
    dana = PREFIX + "shui_dana_" + tag

    gid = "grp_shared_ui_" + tag
    cid = store.create_challenge({"outcome": "shared tool ui check", "title": "Split"},
                                 owner_id=derek, group_id=gid)
    store.join_group(gid, derek)
    store.join_group(gid, dana)
    store.put_user(dana, {"name": "Dana"})
    store.put_node(cid, {"id": "split", "title": "Split the costs",
                         "acceptance_criteria": "x", "depends_on": []})
    shared = store.put_tool(cid, "split", {
        "type": "mini_app", "name": "Cost Split", "source": LEDGER, "usage": "u",
        "smoke_test_passed": True, "degraded": False, "shared": True})
    personal = store.put_tool(cid, "split", {
        "type": "mini_app", "name": "My Hours", "source": LEDGER, "usage": "u",
        "smoke_test_passed": True, "degraded": False, "shared": False})
    _p(f"seeded : {cid}  shared={shared}  personal={personal}")

    bad: list[str] = []

    def check(label: str, got, want) -> None:
        ok = got == want
        _p(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
        if not ok:
            bad.append(label)

    def contains(label: str, got: str, needle: str) -> None:
        ok = needle.lower() in (got or "").lower()
        _p(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {needle!r})"))
        if not ok:
            bad.append(label)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx, page, uid = open_as(browser, base, derek, f"{base}/app?id={cid}")
            try:
                # `open_as` may sign in as a real Google-verified uid that is not the
                # seeded one. Put whoever actually arrived on the party, or every read
                # below is a 403 and the check reports a permissions bug it invented.
                _p(f"browser is {uid!r} (seeded owner {derek!r})")
                if uid != derek:
                    store.join_group(gid, uid)
                    page.reload(wait_until="networkidle", timeout=90000)
                    page.wait_for_timeout(2500)
                # Wait for the dashboard to actually arrive rather than sleeping a
                # guessed number of seconds. `toolsById` is filled by `refresh()`, and
                # a fixed wait that is slightly too short reports "the tool would not
                # open" -- a bug in the product that does not exist.
                page.evaluate("() => refresh(true)")
                page.wait_for_function(
                    "id => typeof toolsById !== 'undefined' && !!toolsById[id]",
                    arg=shared, timeout=30000)
                _p(f"loaded : {page.evaluate('() => Object.keys(toolsById).length')} tools "
                   f"on {page.evaluate('() => challengeId')}")

                _p("\n1. it says it is shared, before anyone has touched it")
                page.evaluate("id => openTool(id)", shared)
                page.wait_for_selector("#frame", timeout=20000)
                page.wait_for_timeout(900)
                badge = page.locator("#m-shared")
                check("badge is visible", badge.is_visible(), True)
                contains("badge text", badge.inner_text(), "shared")

                _p("\n2. Dana saves underneath him")
                r = requests.put(
                    f"{base}/api/challenges/{cid}/tools/{shared}/state",
                    headers={"Authorization": "Bearer " + mint(dana)},
                    json={"state": {"total": "120"}}, timeout=60)
                check("her save", r.status_code, 200)

                _p("\n3. he writes, and is refused rather than silently losing it")
                page.frame_locator("#frame").locator("body").evaluate(
                    "() => window.setTotal('999')")
                # Longer than the 800ms debounce, then the round trip and the 1.2s the
                # client waits before reloading so the warning is readable.
                page.wait_for_timeout(4000)
                warn = page.locator("#m-stage .savewarn")
                check("he is warned", warn.count() > 0, True)
                if warn.count():
                    contains("warning names her", warn.first.inner_text(), "Dana")

                _p("\n4. and the tool comes back showing hers")
                page.wait_for_timeout(1500)
                shown = page.frame_locator("#frame").locator("#out").inner_text()
                check("value in the frame", shown, "120")

                _p("\n5. the badge does not follow him to a personal tool")
                page.evaluate("id => openTool(id)", personal)
                page.wait_for_selector("#frame", timeout=20000)
                page.wait_for_timeout(900)
                check("badge is gone", page.locator("#m-shared").is_visible(), False)
            finally:
                page.screenshot(path="_shared_tool.png", full_page=True)
                ctx.close()
                browser.close()
    finally:
        for tid in (shared, personal):
            for who in (derek, dana):
                store.delete("tool_state", store.tool_state_key(tid, who, False))
            store.delete("tool_state", store.tool_state_key(tid, "", True))
            store.delete("tools", tid)
        store.delete("nodes", f"{cid}:split")
        store.delete("groups", gid)
        store.delete("challenges", cid)
        store.delete("users", dana)
        _p(f"\ncleaned: {cid}")

    if bad:
        _p(f"\nFAIL: {len(bad)} -- " + "; ".join(bad))
        return 1
    _p("\nPASS: a shared tool says so, and a teammate's save stops yours with an "
       "explanation instead of eating it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
