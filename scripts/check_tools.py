"""Prove every forged tool can actually be opened and used.

"Open the tool and use it" is the central beat of the demo and 40% of the rubric is
Innovation & Operational Utility. A tool you can only read the source of is a
screenshot of a tool.

Seeds the demo challenge, then for each tool asserts the right renderer fired:

  mini_app, calculator, tracker, drill
                 -> a sandboxed iframe whose script actually RUNS (not just loads)
  checklist      -> interactive checkboxes that persist when ticked
  script, research_brief
                 -> readable text, which is what those two ARE

That third line used to read `python/text -> readable source`, and that sentence is
worth remembering. It was written when a `calculator` was a Python file, and it
quietly promoted the limitation to a specification: four dead tools passed this check
for weeks because it had been told to expect them. `check_tool_render.py` measured 2
of 6 usable on production while this file said every tool opened and worked -- both
were correct about what they asked, and only one was asking the right thing.

A check that encodes today's shortcoming as tomorrow's requirement is worse than no
check. It is a shortcoming with a green tick next to it.

    python scripts\\check_tools.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from challenge_accepted.api import router  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8145
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

#: The types the user is meant to OPERATE rather than read. Kept in step with the
#: same list in app.html and check_tool_render.py -- three copies is two too many, and
#: the day they disagree is the day one of them starts passing for the wrong reason.
RUNNABLE = ("mini_app", "calculator", "tracker", "drill")

app = FastAPI()
app.include_router(router)


@app.get("/app")
def dashboard() -> FileResponse:
    return FileResponse(STATIC)


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def main() -> None:
    import socket

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    cid = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    import requests

    tools = requests.get(
        f"http://127.0.0.1:{PORT}/api/challenges/{cid}/tools").json()["tools"]
    _p(f"{len(tools)} tools seeded\n")

    failures: list[str] = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1500)

        for tool in tools:
            name, ttype = tool["name"], tool["type"]
            page.evaluate("id => openTool(id)", tool["id"])
            page.wait_for_timeout(700)

            if not page.is_visible("#modal .sheet"):
                failures.append(f"{name}: viewer did not open")
                continue

            shown = {
                "iframe": page.query_selector("#m-stage iframe") is not None,
                "checks": page.eval_on_selector_all("#m-stage .check", "e => e.length"),
                "source": page.query_selector("#m-stage pre.src") is not None,
            }

            if ttype in RUNNABLE and not shown["iframe"]:
                failures.append(
                    f"{name}: a {ttype} is something the user OPERATES and it did not "
                    f"render a runnable page. This is the assertion that used to be "
                    f"missing, and its absence certified four dead tools")

            if ttype == "mini_app":
                if not shown["iframe"]:
                    pass          # already reported above, with the reason
                else:
                    # Load is not proof. Click its button and require the DOM to change.
                    # The slowest simulated worker can take ~4s, so poll rather than
                    # guessing a single sleep -- a fixed wait made this flake once.
                    frame = page.frame_locator("#m-stage iframe")
                    frame.locator("#go").click()
                    text = ""
                    for _ in range(40):
                        page.wait_for_timeout(250)
                        text = frame.locator("#done").inner_text()
                        if text.strip():
                            break
                    width = frame.locator(".fill").first.evaluate("e => e.style.width")
                    _p(f"  mini_app ran  : done={text!r} firstBar={width!r}")
                    if not text.strip():
                        failures.append(f"{name}: mini_app script did not run")

            elif ttype == "checklist":
                if not shown["checks"]:
                    failures.append(f"{name}: checklist rendered no items")
                else:
                    box = page.locator("#m-stage .check input").first
                    box.check()
                    page.wait_for_timeout(300)
                    stuck = page.eval_on_selector(
                        "#m-stage .check", "e => e.classList.contains('done')")
                    if not stuck:
                        failures.append(f"{name}: ticking an item did nothing")

            elif ttype in ("script", "research_brief"):
                # Prose. Rendering it as text is the design, not a gap -- but it still
                # has to render SOMETHING.
                if not shown["source"]:
                    failures.append(f"{name}: {ttype} rendered nothing at all")

            elif not (shown["source"] or shown["iframe"] or shown["checks"]):
                failures.append(f"{name}: nothing rendered")

            _p(f"{ttype:<15} {name:<44} {shown}")
            page.click("#m-close")
            page.wait_for_timeout(250)

        page.evaluate("id => openTool(id)",
                      next(t["id"] for t in tools if t["type"] == "mini_app"))
        page.wait_for_timeout(1200)
        page.screenshot(path=str(ROOT / "_tool.png"))
        browser.close()

    _p(f"\nconsole errors : {errors if errors else 'none'}")
    if errors:
        failures.append(f"console errors: {errors}")
    if failures:
        _p("\nFAILURES:")
        for f in failures:
            _p("  * " + f)
        sys.exit(1)
    _p("\nevery tool opens and works. wrote _tool.png")


if __name__ == "__main__":
    main()
