"""Render docs/architecture.html to a PNG a judge can just look at.

The rules require "an Architecture Diagram with a clear visual representation of your
system". The diagram has always existed as an inline SVG in an HTML page, which is the
right source of truth -- it diffs, and a stale box is visible in review. It is the
wrong DELIVERABLE: Devpost takes an image, and asking a judge to download and open an
HTML file to see your architecture is asking for the one thing they will not do.

So: one source, two artefacts. Edit the HTML, run this, commit both.

    python scripts\\render_architecture.py

Writes docs/architecture.png at 2x for legibility when it is scaled down in a
submission page, and fails loudly if the SVG has grown past its own viewBox -- which
is exactly what happens when somebody adds a line to a card and does not grow the box
under it, and which is invisible in a browser that happily draws outside the frame.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "architecture.html"
OUT = ROOT / "docs" / "architecture.png"
SCALE = 2


def main() -> int:
    from playwright.sync_api import sync_playwright

    if not SRC.exists():
        print(f"missing {SRC}")
        return 2

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(device_scale_factor=SCALE)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(SRC.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(400)

        box = page.evaluate("""() => {
          const svg = document.querySelector('svg');
          const vb = svg.viewBox.baseVal;
          // getBBox is the union of everything actually drawn. If it reaches past the
          // viewBox, content is being clipped or is floating outside the frame -- the
          // signature of a text line added to a card whose rect was never grown.
          const b = svg.getBBox();
          return {vbW: vb.width, vbH: vb.height,
                  x: b.x, y: b.y, w: b.width, h: b.height};
        }""")

        overflow = []
        if box["x"] + box["w"] > box["vbW"] + 1:
            overflow.append(f"content reaches x={box['x'] + box['w']:.0f} past "
                            f"viewBox width {box['vbW']:.0f}")
        if box["y"] + box["h"] > box["vbH"] + 1:
            overflow.append(f"content reaches y={box['y'] + box['h']:.0f} past "
                            f"viewBox height {box['vbH']:.0f}")

        page.locator("svg").screenshot(path=str(OUT))
        browser.close()

    print(f"viewBox   : {box['vbW']:.0f} x {box['vbH']:.0f}")
    print(f"drawn     : {box['w']:.0f} x {box['h']:.0f} "
          f"(ends at {box['x'] + box['w']:.0f}, {box['y'] + box['h']:.0f})")
    print(f"wrote     : {OUT.relative_to(ROOT)}  ({OUT.stat().st_size // 1024} KB, "
          f"{SCALE}x)")
    if errors:
        print(f"page errors: {errors}")
        return 1
    if overflow:
        print("\n--- problems ---")
        for o in overflow:
            print(" * " + o)
        print(" * grow the viewBox (and the band rect) or the diagram is cropped in "
              "the PNG even though the browser draws it fine")
        return 1
    print("\nPASS: the diagram fits its own frame and rendered clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
