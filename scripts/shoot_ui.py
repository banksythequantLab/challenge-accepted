"""Seed data, serve the app, screenshot the dashboard. Proof it renders.

Runs the real FastAPI app in a background thread so the screenshot goes through the
real API, not a mock.

    python scripts\\shoot_ui.py       ->  _ui.png
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

PORT = 8137
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

app = FastAPI()
app.include_router(router)


@app.get("/app")
def dashboard() -> FileResponse:
    return FileResponse(STATIC)


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def main() -> None:
    seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not installed: pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950},
                                device_scale_factor=2)
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"http://127.0.0.1:{PORT}/app", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(ROOT / "_ui.png"), full_page=False)

        # Click a node so the detail panel is exercised too.
        node = page.query_selector(".node")
        if node:
            node.click()
            page.wait_for_timeout(600)
            page.screenshot(path=str(ROOT / "_ui_detail.png"))

        counts = page.eval_on_selector_all(".node", "els => els.length")
        entries = page.eval_on_selector_all("#journal .entry", "els => els.length")
        facts = page.eval_on_selector_all("#facts li", "els => els.length")
        browser.close()

    print(f"\nrendered nodes   : {counts}")
    print(f"journal entries  : {entries}")
    print(f"group facts      : {facts}")
    print(f"console errors   : {errors if errors else 'none'}")
    print("wrote _ui.png and _ui_detail.png")


if __name__ == "__main__":
    main()
