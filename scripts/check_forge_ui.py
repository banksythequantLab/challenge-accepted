"""The FORGE beat, watched while it happens.

Two things were wrong with the most important sixty seconds of the demo:

  1. `setInterval(() => { if (!busy) refresh(); }, 4000)` suppressed the ENTIRE read
     side for the whole length of a run. The map growing from nothing to eleven nodes,
     the journal filling with agent decisions, the tool counter ticking up -- none of
     it rendered until the run ended, at which point the screen snapped to the finished
     state. The most impressive thing this system does was invisible while it did it.

  2. Four Toolwrights building concurrently rendered as an anonymous column of
     "writing code...", which reads as one agent stuttering, not as parallelism.

This replays a SYNTHETIC ADK event stream rather than paying for a real FORGE run:
what changed is client-side, the event shapes are fixed, and a deterministic stream can
assert on timing -- which a live run cannot. The real streaming path is covered by
drive_chat.py.

    python scripts\\check_forge_ui.py
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402

from challenge_accepted.api import router  # noqa: E402
from challenge_accepted.config import FORGE_WORKERS  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8144
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"
APP = "challenge_accepted"

#: Counts read-side polls so we can prove the UI kept refreshing DURING the stream.
polls = {"n": 0}
CID = {"id": ""}

app = FastAPI()


@app.middleware("http")
async def count_polls(request: Request, call_next):
    if request.url.path.startswith("/api/challenges/") and request.method == "GET":
        polls["n"] += 1
    return await call_next(request)


app.include_router(router)


@app.get("/app")
def dashboard() -> FileResponse:
    return FileResponse(STATIC)


@app.post("/apps/{a}/users/{u}/sessions")
async def create_session(a: str, u: str, body: dict):
    return {"id": body.get("session_id") or "s_fake", "state": body.get("state") or {}}


@app.get("/apps/{a}/users/{u}/sessions/{s}")
async def get_session(a: str, u: str, s: str):
    return {"id": s, "state": {"challenge_id": CID["id"]}}


def ev(author: str, **part) -> str:
    return "data: " + json.dumps({"author": author, "content": {"parts": [part]}}) + "\n\n"


#: One realistic FORGE turn: a coordinator, four workers overlapping, one failing its
#: smoke test and retrying, and one idle slot. Spacing is deliberate -- the lanes must
#: interleave, because sequential blocks would prove nothing about parallelism.
SCRIPT: list[tuple[float, str]] = [
    (0.2, ev("warden", text="Building the tools each step needs.")),
    (0.3, ev("quartermaster", functionCall={"name": "save_goal_graph"})),
    (0.3, ev("toolwright_0", text="Taking spec for pacing calculator.")),
    (0.1, ev("toolwright_2", text="Taking spec for the checklist.")),
    (0.2, ev("toolwright_1", text="Taking spec for the hosting brief.")),
    # The rail builds a lane per worker on demand, so the only way to know it copes
    # with the CURRENT fan-out is to drive the current fan-out. This script simulated
    # four workers long after production went to eight -- not wrong about the product,
    # just quietly testing a narrower thing than ships. The high slots are the ones
    # that would break a fixed-height rail or an off-screen overflow, and they were
    # never exercised.
    *[(0.05, ev(f"toolwright_{i}", text="Taking spec for a tool."))
      for i in range(4, FORGE_WORKERS)],
    *[(0.05, ev(f"toolwright_{i}", functionCall={"name": "save_tool"}))
      for i in range(4, FORGE_WORKERS)],
    # Slot 3 stays the idle one. An empty slot has to READ as idle rather than as a
    # worker that died, which is a distinction the rail exists to make.
    (0.2, ev("toolwright_3", text="idle")),
    (0.3, ev("toolwright_0", executableCode={"code": "print(1)"})),
    (0.2, ev("toolwright_2", executableCode={"code": "print(2)"})),
    (0.3, ev("toolwright_1", executableCode={"code": "print(3)"})),
    (0.4, ev("toolwright_2", codeExecutionResult={"outcome": "OUTCOME_FAILED"})),
    (0.3, ev("toolwright_0", codeExecutionResult={"outcome": "OUTCOME_OK"})),
    (0.3, ev("toolwright_2", executableCode={"code": "print(2)  # fixed"})),
    (0.3, ev("toolwright_0", functionCall={"name": "save_tool"})),
    (0.3, ev("toolwright_1", codeExecutionResult={"outcome": "OUTCOME_OK"})),
    (0.4, ev("toolwright_2", codeExecutionResult={"outcome": "OUTCOME_OK"})),
    (0.2, ev("toolwright_1", functionCall={"name": "save_tool"})),
    (0.3, ev("toolwright_2", functionCall={"name": "save_tool"})),
    (0.3, ev("warden", text="Three tools built. One step needed nothing.")),
]


@app.post("/run_sse")
async def run_sse():
    async def gen():
        for delay, chunk in SCRIPT:
            await asyncio.sleep(delay)
            yield chunk
    return StreamingResponse(gen(), media_type="text/event-stream")


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"))


def main() -> None:
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"FAIL: something is already listening on {PORT}. Kill it first.")

    CID["id"] = seed()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(2.0)

    failures: list[str] = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 940})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(f"http://127.0.0.1:{PORT}/app?id={CID['id']}", wait_until="networkidle")
        page.wait_for_timeout(1000)

        page.fill("#input", "Build the tools.")
        polls_before = polls["n"]
        page.click("#send")

        # Mid-stream. The rail must already be up and more than one lane must be live,
        # because the whole point is that they overlap.
        page.wait_for_selector("#forge.on .lane", timeout=8000)
        page.wait_for_timeout(1600)
        mid_lanes = page.eval_on_selector_all(".lane", "els => els.length")
        mid_states = page.eval_on_selector_all(
            ".lane", "els => els.map(e => e.querySelector('.what').innerText)")
        _p(f"mid-stream   : {mid_lanes} lanes {mid_states}")
        if mid_lanes < 2:
            failures.append(f"only {mid_lanes} lane(s) visible mid-stream -- "
                            "parallelism is not on screen")

        # The read side must not be frozen. This is the regression that mattered most.
        polls_mid = polls["n"]
        _p(f"polls during : {polls_mid - polls_before} (must be > 0)")
        if polls_mid <= polls_before:
            failures.append("the read side did not refresh at all during the run -- "
                            "the map and journal are frozen while the agents work")

        page.wait_for_function("() => !document.getElementById('send').disabled",
                               timeout=30000)
        page.wait_for_timeout(600)

        lanes = page.eval_on_selector_all(
            ".lane",
            """els => els.map(e => ({
                 who: e.querySelector('b').innerText,
                 what: e.querySelector('.what').innerText,
                 done: e.classList.contains('done'),
                 bad: e.classList.contains('bad'),
               }))""")
        bylines = page.eval_on_selector_all(
            ".msg.act .byline", "els => [...new Set(els.map(e => e.innerText))]")
        # An idle slot says "idle" once per loop pass. Four slots over several passes
        # buries the real work under bubbles that say nothing; the rail carries it.
        idle_bubbles = page.eval_on_selector_all(
            ".msg.bot",
            "els => els.filter(e => /^idle$/i.test(e.querySelector('.body').innerText.trim())).length")
        page.screenshot(path=str(ROOT / "_forge.png"))
        browser.close()

    _p("\nfinal lanes:")
    for l in lanes:
        _p(f"  {l['who']:<14} {l['what']:<20} done={l['done']} bad={l['bad']}")
    _p(f"\nattributed to : {sorted(bylines)}")
    _p(f"console errors: {errors if errors else 'none'}")

    order = [l["who"] for l in lanes]
    if order != sorted(order):
        failures.append(f"lanes are out of order ({order}) -- they will reshuffle on "
                        "screen and look like a bug")
    # Derived from the script, not written down twice. Hardcoded at 4 and 3, these
    # two lines reported three failures the day the fan-out went to eight -- about a
    # rail that had rendered all eight lanes, in order, with no console errors. An
    # expectation that has to be edited by hand every time the product changes is an
    # expectation that will one day be edited to match a bug.
    expected_lanes = FORGE_WORKERS
    expected_shipped = FORGE_WORKERS - 1   # slot 3 is the idle one
    if len(lanes) != expected_lanes:
        failures.append(f"expected {expected_lanes} worker lanes, got {len(lanes)}")
    shipped = [l for l in lanes if l["done"]]
    if len(shipped) != expected_shipped:
        failures.append(
            f"expected {expected_shipped} lanes to finish shipped, got {len(shipped)}")
    if any(l["bad"] for l in lanes):
        failures.append("a lane is still marked failed after its retry succeeded")
    idle = [l for l in lanes if "idle" in l["what"].lower()]
    if not idle:
        failures.append("the idle worker is not shown as idle")
    _p(f"idle bubbles  : {idle_bubbles} (must be 0)")
    if idle_bubbles:
        failures.append(f"{idle_bubbles} empty 'idle' bubble(s) in the transcript -- "
                        "they bury the real work on camera")
    if len(bylines) < 3:
        failures.append(f"action chips attributed to only {len(bylines)} agent(s) -- "
                        "parallel work reads as one agent stuttering")
    if errors:
        failures.append(f"console errors: {errors}")

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    _p("\nthe forge beat is visible while it runs. wrote _forge.png")


if __name__ == "__main__":
    main()
