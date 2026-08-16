"""Can you use this without a mouse, and can you read it?

Not a box-ticking exercise. Three concrete things a judge might actually hit:

  1. THE QUEST MAP IS AN SVG. Nodes are <g> elements with click handlers, which are
     invisible to the keyboard and announced as nothing by a screen reader. The map is
     the product's centrepiece; if it is mouse-only then the centrepiece is mouse-only.

  2. THE TOOL VIEWER IS A MODAL. A modal that does not take focus leaves the keyboard
     user tabbing through the page behind it, and one that does not close on Escape
     traps them. Both are easy to get wrong and neither is visible in a screenshot.

  3. CONTRAST. This is a dark theme built by eye. Body text under 4.5:1 is unreadable
     on a projector, which is where a hackathon demo is most likely to be seen.

Contrast is computed from the rendered colours rather than the stylesheet, so it
accounts for whatever actually won the cascade.

    python scripts\\check_a11y.py
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from challenge_accepted.api import router  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8149
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

#: WCAG 2.1 AA: 4.5:1 for body text, 3:1 for large text (>=18.66px bold or >=24px).
AA_BODY = 4.5
AA_LARGE = 3.0

app = FastAPI()
app.include_router(router)


@app.get("/app")
def dashboard() -> FileResponse:
    return FileResponse(STATIC)


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


#: Contrast, computed in the page against the effective background -- walking up the
#: ancestors until something is not transparent, which is what a browser actually paints.
CONTRAST_JS = """
(sel) => {
  const lum = ([r, g, b]) => {
    const f = c => { c /= 255; return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); };
    return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b);
  };
  const parse = s => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number);
  const bgOf = el => {
    for (let n = el; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor;
      const a = (c.match(/[\\d.]+/g) || [])[3];
      if (c && c !== 'transparent' && a !== '0') return parse(c);
    }
    return [11, 13, 18];
  };
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!el.offsetParent && el.tagName !== 'BODY') continue;
    const text = (el.textContent || '').trim();
    if (!text) continue;
    const cs = getComputedStyle(el);
    const [f, b] = [parse(cs.color), bgOf(el)];
    const [L1, L2] = [lum(f), lum(b)].sort((x, y) => y - x);
    const size = parseFloat(cs.fontSize);
    const large = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight) >= 700);
    out.push({
      what: text.slice(0, 42).replace(/\\s+/g, ' '),
      ratio: +((L1 + 0.05) / (L2 + 0.05)).toFixed(2),
      size, large, sel: el.className || el.tagName,
    });
  }
  return out;
}
"""


def main() -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    cid = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    failures: list[str] = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 940})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{PORT}/app?id={cid}", wait_until="networkidle")
        page.wait_for_timeout(1200)

        # --- 1. the quest map, by keyboard --------------------------------------
        focusable = page.eval_on_selector_all(
            ".node", "els => els.filter(e => e.tabIndex >= 0).length")
        total = page.eval_on_selector_all(".node", "els => els.length")
        labelled = page.eval_on_selector_all(
            ".node",
            "els => els.filter(e => e.getAttribute('aria-label')"
            " || e.getAttribute('role') === 'button').length")
        _p(f"quest nodes      : {total} ({focusable} reachable by keyboard, "
           f"{labelled} labelled)")
        if focusable < total:
            failures.append(f"{total - focusable} of {total} quest nodes cannot be "
                            "reached by keyboard -- the map is mouse-only")
        if labelled < total:
            failures.append(f"{total - labelled} of {total} quest nodes have no "
                            "accessible name")

        if focusable:
            # Tab to a node and open it with the keyboard.
            page.eval_on_selector(".node", "e => e.focus()")
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
            opened = page.is_visible("#detail h3")
            _p(f"Enter opens quest: {opened}")
            if not opened:
                failures.append("focusing a quest node and pressing Enter does nothing")

        # --- 2. the tool modal --------------------------------------------------
        # Select a node that HAS a tool, by keyboard. The first version tabbed to an
        # arbitrary node, found no Open tool button and reported "the seed did not
        # attach one" -- a probe blaming the fixture for its own sloppiness.
        picked = page.evaluate(
            """() => {
                 const n = [...document.querySelectorAll('.node')]
                   .find(e => e.querySelector('circle'));
                 if (!n) return null;
                 n.focus();
                 return n.getAttribute('aria-label');
               }""")
        _p(f"node with a tool : {picked!r}")
        if picked:
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
        if page.is_visible("[data-open]"):
            # Focus it first, so we can assert focus RETURNS here on close.
            page.eval_on_selector("[data-open]", "e => e.focus()")
            page.keyboard.press("Enter")
            page.wait_for_selector("#modal.on", timeout=5000)
            inside = page.evaluate(
                "() => document.getElementById('modal')"
                ".contains(document.activeElement)")
            _p(f"modal takes focus: {inside}")
            if not inside:
                failures.append("opening the tool viewer leaves focus on the page "
                                "behind it, so a keyboard user is still in the map")

            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            closed = not page.is_visible("#modal.on")
            _p(f"Escape closes    : {closed}")
            if not closed:
                failures.append("Escape does not close the tool viewer -- a keyboard "
                                "user is trapped in it")
            if closed:
                back = page.evaluate(
                    "() => document.activeElement && "
                    "(document.activeElement.dataset.open ? 'the Open tool button' "
                    " : document.activeElement.tagName)")
                _p(f"focus returns to : {back}")
                if back != "the Open tool button":
                    failures.append(f"after closing, focus went to {back} instead of "
                                    "the button that opened it")
        else:
            failures.append("no tool to open -- the seed did not attach one")

        # --- 3. contrast, in BOTH themes ----------------------------------------
        #
        # A light theme is where contrast quietly dies: the same #FFC24B that reads
        # fine on near-black is 1.7:1 on white. Measuring only the theme you happen to
        # be looking at means shipping the other one blind.
        page.click('.tab[data-p="chat"]')
        page.wait_for_timeout(300)
        SELECTORS = (".msg .body, .who, .stat span, .stat b, .legend span, "
                     ".roster, .facts li, .entry, .lane .what, #title, .crit, "
                     ".kind, .tool .t, .byline, .gatecard p, .empty")
        bad: list[tuple[str, float, str]] = []
        shots = ROOT / "_walk"
        shots.mkdir(exist_ok=True)

        for theme in ("dark", "light"):
            page.evaluate("t => document.documentElement.dataset.theme = t", theme)
            page.wait_for_timeout(400)
            rows = page.evaluate(CONTRAST_JS, SELECTORS)
            worst = sorted({(r["what"], r["ratio"], r["large"], str(r["sel"]))
                            for r in rows}, key=lambda r: r[1])[:8]
            _p(f"\nlowest contrast ({theme}):")
            for what, ratio, large, sel in worst:
                need = AA_LARGE if large else AA_BODY
                flag = "  <-- below AA" if ratio < need else ""
                _p(f"  {ratio:>5}:1  need {need}  {str(sel)[:22]:<22} {what!r}{flag}")
            bad += [(f"[{theme}] {w}", r, s)
                    for w, r, lg, s in worst if r < (AA_LARGE if lg else AA_BODY)]
            page.screenshot(path=str(shots / f"a11y_{theme}.png"))

        browser.close()

    for what, ratio, sel in bad:
        failures.append(f"{ratio}:1 contrast on {sel} ({what!r}) is below WCAG AA")
    if errors:
        failures.append(f"page errors: {errors}")

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    _p("\nusable without a mouse, and readable in both themes. "
       "wrote _walk/a11y_dark.png and _walk/a11y_light.png")


if __name__ == "__main__":
    main()
