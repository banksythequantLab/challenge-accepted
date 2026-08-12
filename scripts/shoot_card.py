"""Screenshot the business-model card, and refuse to ship it if it overflows.

A pricing slide that clips the bottom row on the presenter's screen is a slide that
gets read out loud instead of shown. Renders at 1920x1080 -- the size it will actually
be full-screened at -- and fails if the content is taller than the viewport or if any
tier column has collapsed.

    python scripts\\shoot_card.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "docs" / "business_model.html"
OUT = ROOT / "docs" / "business_model.png"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def main() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080},
                                device_scale_factor=2)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(CARD.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(400)

        doc_h = page.evaluate("() => document.documentElement.scrollHeight")
        view_h = page.evaluate("() => window.innerHeight")
        cols = page.eval_on_selector(
            ".tiers", "e => getComputedStyle(e).gridTemplateColumns")
        prices = page.eval_on_selector_all(
            ".price", "els => els.map(e => e.innerText.trim().replace(/\\s+/g,' '))")
        page.screenshot(path=str(OUT))
        browser.close()

    _p(f"content height : {doc_h}px in a {view_h}px viewport")
    _p(f"tier columns   : {cols}")
    _p(f"prices         : {prices}")
    _p(f"page errors    : {errors if errors else 'none'}")

    if doc_h > view_h + 2:
        sys.exit(f"FAIL: card overflows by {doc_h - view_h}px at 1920x1080")
    if len(cols.split()) != 4:
        sys.exit(f"FAIL: tiers did not lay out in 4 columns ({cols})")
    if len(prices) != 4:
        sys.exit(f"FAIL: expected 4 prices, found {len(prices)}")
    if errors:
        sys.exit(f"FAIL: page errors {errors}")

    _p(f"\ncard fits and renders. wrote {OUT.name}")


if __name__ == "__main__":
    main()
