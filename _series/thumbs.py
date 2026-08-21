"""Episode thumbnails, in the docket's visual language.

One number carries the frame, three words explain it, an episode chip anchors it.
Same palette as the tracker page -- cool industrial ground, safety orange, deep
teal for anything that is actually built -- so the series reads as one thing.

Text stays inside the middle 80% of the frame. YouTube stamps a duration badge over
the bottom-right corner and crops the edges on some surfaces; a word that lands
under that badge is a word nobody reads.

Add a row to EPISODES and re-run. Nothing else to edit.

    python _series\\thumbs.py    ->  _series\\thumbs\\ep01.png ...
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "thumbs"
OUT.mkdir(exist_ok=True)

#: (slug, episode chip, the number, what the number is, the hook line)
EPISODES = [
    ("ep01", "DAY 0", "25", "signed clients needed",
     "The first thing it told me to do was arithmetic"),
    ("ep02", "DAY 1", "34", "domains, ranked",
     "It says five of them matter"),
]

CSS = """
*{box-sizing:border-box}
html,body{margin:0;width:1280px;height:720px;overflow:hidden;background:#10151A;
 color:#E6ECF1;font:400 24px/1.4 "Source Sans 3","Segoe UI",system-ui,sans-serif}
.f{position:absolute;inset:0;padding:72px 128px;display:flex;flex-direction:column;
 justify-content:center}
/* a hairline grid, barely there -- job-site drawing paper, not a "tech" grid */
.g{position:absolute;inset:0;opacity:.13;
 background-image:linear-gradient(#2A343E 1px,transparent 1px),
 linear-gradient(90deg,#2A343E 1px,transparent 1px);background-size:80px 80px}
.chip{align-self:flex-start;font:600 22px/1 "JetBrains Mono",Consolas,monospace;
 letter-spacing:.22em;color:#1A1005;background:#F07C2B;padding:11px 16px;
 border-radius:3px;margin-bottom:34px}
.n{font:800 250px/.82 Archivo,sans-serif;letter-spacing:-.045em;color:#F07C2B;
 margin:0}
.k{margin-top:14px;font:600 34px/1.2 Archivo,sans-serif;color:#93A0AD;
 letter-spacing:-.01em}
.hook{margin-top:30px;font:600 46px/1.16 Archivo,sans-serif;letter-spacing:-.02em;
 color:#E6ECF1;max-width:15ch}
.brand{position:absolute;left:128px;bottom:56px;
 font:600 21px/1 "JetBrains Mono",Consolas,monospace;letter-spacing:.14em;
 color:#6C7986}
"""


def frame(chip: str, n: str, k: str, hook: str) -> str:
    return (f"<!doctype html><meta charset=utf-8>"
            f'<link rel=stylesheet href="https://fonts.googleapis.com/css2?'
            f"family=Archivo:wght@600;800&family=Source+Sans+3:wght@400;600"
            f'&family=JetBrains+Mono:wght@600&display=swap">'
            f"<style>{CSS}</style><div class=g></div><div class=f>"
            f'<div class=chip>{chip}</div>'
            f'<div class=n>{n}</div><div class=k>{k}</div>'
            f'<div class=hook>{hook}</div></div>'
            f'<div class=brand>CHALLENGEACCEPTED.APP</div>')


def main() -> int:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 720})
        for slug, chip, n, k, hook in EPISODES:
            pg.set_content(frame(chip, n, k, hook))
            # the webfonts come off the network; screenshotting before they land
            # silently ships a fallback-face thumbnail
            pg.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)
            pg.wait_for_timeout(250)
            pg.screenshot(path=str(OUT / f"{slug}.png"))
            print(f"  {slug}.png")
        b.close()
    print(f"\n{len(EPISODES)} thumbnails -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
