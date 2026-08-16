"""Record the demo footage by driving the deployed product for real.

Nothing here is staged. It signs in, types a goal, answers the interview, and sits
through the whole FORGE run against https://challengeaccepted.app -- so what ends up on
screen is the product working, at the speed it actually works. `cut_demo.py` does the
speeding up afterwards, which is an editing decision rather than a claim.

Writes:
  _video/raw/*.webm   one file per browser context (owner, teammate)
  _video/marks.json   beat -> seconds into that context's recording

    python scripts\\record_demo.py
    python scripts\\record_demo.py --dry     # 60s smoke: sign in, one turn, stop

The run costs real model time (a full build is 3-5 minutes) and leaves a real challenge
behind, owned by the ca_test_ identity it signs in as.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

OUT = ROOT / "_video"
RAW = OUT / "raw"
BASE = "https://challengeaccepted.app"

#: 1280x720 on purpose. A wider capture fits more UI, and then every word on screen is
#: proportionally smaller in the finished video -- the first cut recorded at 1600x900
#: and the chat was unreadable once it was scaled to fit a Devpost player.
SIZE = {"width": 1280, "height": 720}

#: The app follows the machine's colour scheme, and a headless Chromium reports LIGHT.
#: So the first recording came out entirely in the light theme, cutting from a dark
#: title card into a white app. Dark is the identity; the light theme gets its own beat.
SCHEME = "dark"

TURNS = [
    "I want to run a 10k in under 55 minutes by Christmas.",
    "I run about 3k twice a week at a slow pace. I have never trained properly, "
    "and I have no injuries.",
    "I can train four evenings a week for about 45 minutes. It is an official "
    "organised park 10k on Christmas Eve.",
    "That's everything -- accept the challenge, draw the map and build the tools.",
]

TURN_TIMEOUT_MS = 600_000


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


class Marks:
    """Beat timestamps, relative to the moment each context started recording."""

    def __init__(self):
        self.t0: dict[str, float] = {}
        self.beats: list[dict] = []

    def start(self, ctx_name: str) -> None:
        self.t0[ctx_name] = time.perf_counter()

    def at(self, ctx_name: str, beat: str) -> None:
        t = round(time.perf_counter() - self.t0[ctx_name], 2)
        self.beats.append({"ctx": ctx_name, "beat": beat, "t": t})
        _p(f"  [{t:>7.2f}s] {ctx_name}: {beat}")


def type_like_a_person(page, text: str) -> None:
    """Typed, not pasted. `fill()` teleports a sentence into the box in one frame,
    which on camera looks like a cut rather than a person using the product."""
    page.click("#input")
    page.type("#input", text, delay=18)


def main() -> int:
    dry = "--dry" in sys.argv
    if OUT.exists():
        shutil.rmtree(OUT)
    RAW.mkdir(parents=True)

    from playwright.sync_api import sync_playwright
    from testauth import sign_in

    marks = Marks()
    videos: dict[str, str] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-device-scale-factor=1"])

        # ---- the owner ------------------------------------------------------------
        owner = browser.new_context(viewport=SIZE, record_video_dir=str(RAW),
                                    record_video_size=SIZE, color_scheme=SCHEME,
                                    permissions=["clipboard-read", "clipboard-write"])
        page = owner.new_page()
        marks.start("owner")
        page.goto(f"{BASE}/app", wait_until="networkidle", timeout=90_000)
        page.wait_for_selector("#gate-in", timeout=30_000)
        marks.at("owner", "gate")
        page.wait_for_timeout(2200)          # let the sign-in screen breathe

        uid = sign_in(page)
        marks.at("owner", "signed-in")
        _p(f"  signed in as {uid}")
        page.wait_for_timeout(1800)

        for i, text in enumerate(TURNS, 1):
            if dry and i > 1:
                break
            marks.at("owner", f"turn{i}-typing")
            type_like_a_person(page, text)
            page.wait_for_timeout(400)
            page.click("#send")
            marks.at("owner", f"turn{i}-sent")
            try:
                page.wait_for_function(
                    "() => document.getElementById('send').disabled", timeout=15_000)
            except Exception:
                pass
            # The FORGE turn is the one worth watching, and its beats do not arrive in a
            # fixed order or at a fixed time. Waiting for them one after another with a
            # long timeout each is how a run got missed entirely: 180s waiting for the
            # rail, then 180s waiting for the map, on a turn that took 400s — both
            # windows closed before the thing they were watching for happened, and the
            # recording had no money shot in it. Watch for all of them at once, and
            # stop the moment the turn ends.
            if i == len(TURNS):
                seen: set[str] = set()
                watch = {
                    "forge-rail": "#forge.on",
                    "map-drawn": "#graph .node",
                }
                deadline = time.perf_counter() + TURN_TIMEOUT_MS / 1000
                while time.perf_counter() < deadline:
                    if page.evaluate(
                            "() => !document.getElementById('send').disabled"):
                        break
                    for beat, sel in watch.items():
                        if beat not in seen and page.locator(sel).count():
                            marks.at("owner", beat)
                            seen.add(beat)
                    if "first-tool" not in seen:
                        n = page.eval_on_selector(
                            "#c-tools", "e => parseInt(e.textContent.trim()) || 0")
                        if n > 0:
                            marks.at("owner", "first-tool")
                            seen.add("first-tool")
                    page.wait_for_timeout(500)
                for beat in watch:
                    if beat not in seen:
                        _p(f"  (never saw {beat} during the turn)")
            page.wait_for_function(
                "() => !document.getElementById('send').disabled",
                timeout=TURN_TIMEOUT_MS)
            marks.at("owner", f"turn{i}-done")
            page.wait_for_timeout(900)

        cid = page.evaluate("() => new URLSearchParams(location.search).get('id')")
        _p(f"  challenge: {cid}")

        if not dry:
            # ---- a tool, opened ---------------------------------------------------
            page.click('.tab[data-p="quest"]')
            page.wait_for_timeout(700)
            armed = page.evaluate(
                """() => [...document.querySelectorAll('#graph .node')]
                     .filter(n => /,\\s*\\d+\\s+tools?\\b/.test(n.getAttribute('aria-label')||''))
                     .map(n => n.dataset.id)""")
            if armed:
                page.click(f'#graph .node[data-id="{armed[0]}"]')
                page.wait_for_timeout(900)
                marks.at("owner", "node-selected")
                if page.locator("[data-open]").count():
                    page.locator("[data-open]").first.click()
                    page.wait_for_selector("#modal.on", timeout=15_000)
                    marks.at("owner", "tool-open")
                    page.wait_for_timeout(4000)
                    page.click("#m-close")
                    page.wait_for_timeout(700)

            # ---- the invite -------------------------------------------------------
            page.click('.tab[data-p="facts"]')
            page.wait_for_timeout(900)
            marks.at("owner", "party-pane")
            page.click("#invite")
            page.wait_for_timeout(1200)
            link = page.evaluate("() => navigator.clipboard.readText()")
            marks.at("owner", "invite-copied")
            _p(f"  invite: {link}")

            # ---- the teammate, in a second context --------------------------------
            mate_ctx = browser.new_context(viewport=SIZE, record_video_dir=str(RAW),
                                           record_video_size=SIZE, color_scheme=SCHEME)
            mate = mate_ctx.new_page()
            marks.start("mate")
            mate.goto(link, wait_until="networkidle", timeout=90_000)
            mate.wait_for_selector("#gate-in", timeout=30_000)
            marks.at("mate", "gate")
            mate.wait_for_timeout(1500)
            sign_in(mate)
            marks.at("mate", "signed-in")
            mate.wait_for_timeout(2500)

            join = mate.get_by_role("button", name="Join this quest")
            if join.count():
                marks.at("mate", "invited")
                mate.wait_for_timeout(2000)
                join.first.click()
                mate.wait_for_selector("#graph .node", timeout=60_000)
                marks.at("mate", "joined")
                mate.wait_for_timeout(2500)

            mate.click('.tab[data-p="facts"]')
            mate.wait_for_timeout(2500)
            marks.at("mate", "mate-party")

            # The owner's roster ticking 1 -> 2 while they sit still is the single
            # clearest shot in the whole thing, so give the poll time to land.
            page.bring_to_front()
            page.wait_for_timeout(6000)
            marks.at("owner", "roster-grew")

            # ---- light and dark ---------------------------------------------------
            page.click('.tab[data-p="quest"]')
            page.wait_for_timeout(600)
            page.click("#theme")
            marks.at("owner", "theme-light")
            page.wait_for_timeout(3200)
            page.click("#theme")
            marks.at("owner", "theme-dark")
            page.wait_for_timeout(2000)

            videos["mate"] = mate.video.path()
            mate_ctx.close()

        videos["owner"] = page.video.path()
        owner.close()
        browser.close()

    # Playwright only finalises a video when its context closes, so rename after.
    named = {}
    for name, path in videos.items():
        src = Path(path)
        dst = RAW / f"{name}.webm"
        for _ in range(40):
            if src.exists():
                break
            time.sleep(0.25)
        src.rename(dst)
        named[name] = dst.name
        _p(f"  {name}: {dst.name}  ({dst.stat().st_size/1e6:.1f} MB)")

    (OUT / "marks.json").write_text(json.dumps(
        {"base": BASE, "challenge": cid, "videos": named, "beats": marks.beats},
        indent=2), encoding="utf-8")
    _p(f"\nwrote {OUT/'marks.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
