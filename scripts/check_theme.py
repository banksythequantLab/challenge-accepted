"""Both themes, measured -- including the surfaces that quietly stay dark.

A light theme is easy to get 90% right and the last 10% is what people see: one SVG
card still filled near-black, one panel still on a hardcoded hex, one label the same
colour as the paper behind it. None of that shows up in a unit test and all of it
shows up in a screenshot.

So this asserts the thing that actually matters -- that every SURFACE flipped -- by
measuring rendered luminance rather than reading the stylesheet. It also checks the
toggle persists, and that the choice survives a reload without a flash of the wrong
theme, which is the bug you only notice on someone else's laptop.

    python scripts\\check_theme.py            # local, seeded, no cloud
    python scripts\\check_theme.py https://challengeaccepted.app
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

PORT = 8151

#: Every painted surface in the app. If you add a panel and forget to tokenise it,
#: this list is what notices -- so add it here at the same time.
SURFACES = """
() => {
  const parse = (c) => {
    const m = (c || '').match(/[\\d.]+/g);
    if (!m || m.length < 3) return null;
    return [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1];
  };
  const lum = ([r, g, b]) => {
    const f = (x) => { x /= 255; return x <= 0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055, 2.4); };
    return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b);
  };
  // What the eye actually receives, not what the property says.
  //
  // The composer is `rgba(15,23,42,.04)` in the light theme -- a dark ink at 4%
  // opacity, i.e. a barely-there wash over white. Reading the raw value called that a
  // dark surface and failed a theme that was correct. Anything translucent has to be
  // composited over what is behind it before it means anything.
  const painted = (el, prop) => {
    let [r, g, b, a] = parse(getComputedStyle(el)[prop]) || [0, 0, 0, 0];
    let node = prop === 'fill' ? el.parentElement : el.parentElement;
    while (a < 1 && node) {
      const under = parse(getComputedStyle(node).backgroundColor);
      if (under && under[3] > 0) {
        const [ur, ug, ub, ua] = under;
        r = r*a + ur*(1-a); g = g*a + ug*(1-a); b = b*a + ub*(1-a);
        a = a + ua*(1-a);
      }
      node = node.parentElement;
    }
    if (a < 1) {   // still see-through at the root: the page background wins
      const [pr, pg, pb] = parse(getComputedStyle(document.documentElement).backgroundColor)
        || [255, 255, 255, 1];
      r = r*a + pr*(1-a); g = g*a + pg*(1-a); b = b*a + pb*(1-a);
    }
    return [r, g, b];
  };
  const out = {};
  const put = (name, el, prop) => {
    if (!el) return;
    const raw = getComputedStyle(el)[prop];
    if (!parse(raw)) return;
    const rgb = painted(el, prop);
    out[name] = { value: raw, lum: +lum(rgb).toFixed(3) };
  };
  put('body',        document.body, 'backgroundColor');
  put('header',      document.querySelector('header'), 'backgroundColor');
  put('aside',       document.querySelector('aside'), 'backgroundColor');
  put('composer',    document.querySelector('.composer'), 'backgroundColor');
  put('textarea',    document.querySelector('#input'), 'backgroundColor');
  put('bot bubble',  document.querySelector('.msg.bot'), 'backgroundColor');
  put('picker',      document.querySelector('#picker'), 'backgroundColor');
  put('xp track',    document.querySelector('.xpbar'), 'backgroundColor');
  put('node card',   document.querySelector('.node rect.card'), 'fill');
  put('ink',         document.body, 'color');
  return out;
}
"""


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def serve_local() -> str:
    """Boot the app with seeded data, so there is a map and a bubble to measure."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse

    from challenge_accepted.api import router
    from seed_demo import main as seed

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}.")

    cid = seed()
    app = FastAPI()
    app.include_router(router)

    @app.get("/app")
    def dashboard() -> FileResponse:
        return FileResponse(ROOT / "challenge_accepted" / "static" / "app.html")

    threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error"),
        daemon=True).start()
    time.sleep(2.0)
    return f"http://127.0.0.1:{PORT}/app?id={cid}"


def main() -> int:
    remote = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else None
    url = f"{remote}/app" if remote else serve_local()
    bad: list[str] = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # --- the machine's preference is the default -----------------------------
        for scheme, want in (("dark", "dark"), ("light", "light")):
            ctx = browser.new_context(color_scheme=scheme,
                                      viewport={"width": 1400, "height": 900})
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=90000)
            got = page.evaluate("() => document.documentElement.dataset.theme")
            _p(f"OS prefers {scheme:<5} -> app opens in {got}")
            if got != want:
                bad.append(f"a machine set to {scheme} opens the app in {got}")
            ctx.close()

        # --- every surface actually flips ----------------------------------------
        ctx = browser.new_context(color_scheme="dark",
                                  viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: bad.append(f"pageerror: {e}"))
        page.goto(url, wait_until="networkidle", timeout=90000)
        if page.is_visible("#gate"):
            from testauth import sign_in
            sign_in(page)
        page.wait_for_timeout(2500)

        readings = {}
        for theme in ("dark", "light"):
            page.evaluate("t => document.documentElement.dataset.theme = t", theme)
            page.wait_for_timeout(350)
            readings[theme] = page.evaluate(SURFACES)

        _p(f"\n{'surface':<12} {'dark':>26}  {'light':>26}")
        names = sorted(set(readings["dark"]) | set(readings["light"]))
        for name in names:
            d = readings["dark"].get(name)
            l = readings["light"].get(name)
            _p(f"{name:<12} {str(d and d['value'])[:24]:>26}  "
               f"{str(l and l['value'])[:24]:>26}")
            if not d or not l:
                continue
            if name == "ink":
                # Text runs the other way: dark theme = light text.
                if d["lum"] < 0.5:
                    bad.append("dark theme is painting dark TEXT")
                if l["lum"] > 0.5:
                    bad.append("light theme is painting light TEXT")
                continue
            if d["lum"] > 0.5:
                bad.append(f"{name} is a LIGHT surface in the dark theme ({d['value']})")
            if l["lum"] < 0.5:
                bad.append(f"{name} stayed DARK in the light theme ({l['value']}) -- "
                           f"a hardcoded colour that never got tokenised")

        # --- the button, and whether the choice sticks ---------------------------
        page.evaluate("() => document.documentElement.dataset.theme = 'dark'")
        page.click("#theme")
        after = page.evaluate("() => document.documentElement.dataset.theme")
        label = page.eval_on_selector("#theme", "e => e.textContent.trim()")
        _p(f"\ntoggle from dark -> {after}   (button now reads {label!r})")
        if after != "light":
            bad.append(f"clicking the toggle in dark mode gave {after}")
        if label.lower() != "dark":
            bad.append(f"the button offers {label!r} while already in light mode")

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(800)
        kept = page.evaluate("() => document.documentElement.dataset.theme")
        _p(f"after reload      : {kept}")
        if kept != "light":
            bad.append(f"the chosen theme did not survive a reload (got {kept})")

        # An explicit choice must beat the OS, or changing your mind never sticks on a
        # machine whose system theme disagrees.
        ctx2 = browser.new_context(color_scheme="dark",
                                   viewport={"width": 1200, "height": 800},
                                   storage_state=ctx.storage_state())
        p2 = ctx2.new_page()
        p2.goto(url, wait_until="networkidle", timeout=90000)
        overridden = p2.evaluate("() => document.documentElement.dataset.theme")
        _p(f"OS dark + saved light -> {overridden}")
        if overridden != "light":
            bad.append("a saved preference loses to the OS setting")

        shots = ROOT / "_walk"
        shots.mkdir(exist_ok=True)
        for theme in ("dark", "light"):
            page.evaluate("t => document.documentElement.dataset.theme = t", theme)
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / f"theme_{theme}.png"))

        ctx2.close()
        ctx.close()
        browser.close()

    if bad:
        _p("\n--- problems ---")
        for x in dict.fromkeys(bad):
            _p(" * " + x)
        return 1
    _p("\nPASS -- both themes hold up, and the choice sticks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
