"""Screenshot the architecture diagram so layout regressions are visible.

The diagram is hand-authored SVG. Editing card text can overflow a box, and nobody
notices until a judge opens it.

    python scripts\\shoot_arch.py   ->  _arch.png
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "architecture.html"


def main() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1460, "height": 1050})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(DOC.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(600)
        page.screenshot(path=str(ROOT / "_arch.png"), full_page=True)
        browser.close()

    print(f"page errors : {errors if errors else 'none'}")
    print("wrote _arch.png")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
