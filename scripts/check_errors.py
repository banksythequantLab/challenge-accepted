"""What a judge sees when it breaks.

Over a seven-week judging window a run WILL fail: Gemini rate-limits, Cloud Run
recycles an instance mid-stream, wifi drops in a hotel. Until now the user got a dashed
chip reading

    x run_sse 429

-- a status code, no idea whether their work survived, and no way forward except
retyping the message they had just watched scroll into the transcript.

The failure paths were also the least-tested code in the app, for the obvious reason
that they are hard to provoke against a real backend. A fake server makes them trivial:
each scenario returns exactly the failure it is named after.

Scenarios:
  429            rate limited before the stream starts
  500            server error before the stream starts
  truncated      a stream that dies HALFWAY -- the hardest case, because some of the
                 work really did happen and the user has to be told which
  recovers       a run that fails once and succeeds on Try again

    python scripts\\check_errors.py
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
from fastapi import FastAPI, Response  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402

from challenge_accepted.api import router  # noqa: E402
from seed_demo import main as seed  # noqa: E402

PORT = 8148
STATIC = ROOT / "challenge_accepted" / "static" / "app.html"

MODE = {"how": "429", "attempt": 0}
CID = {"id": ""}

app = FastAPI()
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


def ev(author: str, text: str) -> str:
    return "data: " + json.dumps(
        {"author": author, "content": {"parts": [{"text": text}]}}) + "\n\n"


@app.post("/run_sse")
async def run_sse():
    MODE["attempt"] += 1
    how = MODE["how"]

    if how == "429":
        return Response(status_code=429, content="rate limited")
    if how == "500":
        return Response(status_code=500, content="boom")
    # Fail the first TWO attempts, not one. `startRun` already retries once by itself
    # -- that is the session-rebuild path -- so a single transient failure never
    # reaches the user at all. Good behaviour, and worth knowing: to test the USER's
    # Try again you have to get past the client's own retry first.
    if how == "recovers" and MODE["attempt"] <= 2:
        return Response(status_code=429, content="rate limited")

    async def gen():
        yield ev("warden", "Starting on that now.")
        await asyncio.sleep(0.3)
        yield ev("cartographer", "Drawing the map.")
        await asyncio.sleep(0.3)
        if how == "truncated":
            # Die mid-stream, the way a recycled instance does: the client has already
            # rendered real work and then the bytes simply stop.
            raise RuntimeError("instance went away")
        yield ev("warden", "Done.")

    return StreamingResponse(gen(), media_type="text/event-stream")


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="critical")


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

        # Capture page errors. Without this the first run of this script just timed
        # out waiting for an error chip, with no hint that a TypeError inside send()
        # had eaten the whole turn -- including the handler meant to report it.
        crashes: list[str] = []

        def fresh():
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: crashes.append(str(e)))
            pg.on("console",
                  lambda m: crashes.append("console: " + m.text)
                  if m.type == "error" and "Failed to load resource" not in m.text
                  else None)
            pg.goto(f"http://127.0.0.1:{PORT}/app?id={CID['id']}",
                    wait_until="networkidle")
            pg.wait_for_timeout(900)
            return pg

        def run_turn(pg, msg="Do the thing."):
            pg.fill("#input", msg)
            pg.click("#send")
            pg.wait_for_function("() => !document.getElementById('send').disabled",
                                 timeout=30000)
            pg.wait_for_timeout(400)

        # --- 429 -------------------------------------------------------------
        MODE.update(how="429", attempt=0)
        page = fresh()
        run_turn(page)
        err = page.inner_text(".msg.act.err") if page.is_visible(".msg.act.err") else ""
        _p(f"\n429       : {err!r}")
        if "429" in err:
            failures.append("the 429 message still shows a raw status code")
        if "rate" not in err.lower():
            failures.append("the 429 message does not say it is rate limiting")
        if "Nothing was saved" not in err:
            failures.append("a pre-stream failure does not tell the user nothing was saved")
        if not page.is_visible("#retry"):
            failures.append("no Try again after a 429")
        # The message must survive so retrying does not mean retyping.
        page.screenshot(path=str(ROOT / "_err_429.png"))
        page.context.close()

        # --- 500 -------------------------------------------------------------
        MODE.update(how="500", attempt=0)
        page = fresh()
        run_turn(page)
        err = page.inner_text(".msg.act.err")
        _p(f"500       : {err!r}")
        if "500" in err:
            failures.append("the 500 message still shows a raw status code")
        page.context.close()

        # --- truncated mid-stream -------------------------------------------
        MODE.update(how="truncated", attempt=0)
        page = fresh()
        run_turn(page)
        err = page.inner_text(".msg.act.err")
        bots = page.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        _p(f"truncated : {err!r}")
        _p(f"            kept {len(bots)} agent message(s) on screen")
        if "on the map" not in err:
            failures.append("a mid-stream failure does not say the partial work survived")
        if "Nothing was saved" in err:
            failures.append("a mid-stream failure wrongly claims nothing was saved")
        if len(bots) < 2:
            failures.append("the agent text that DID arrive was thrown away on failure")
        page.screenshot(path=str(ROOT / "_err_stream.png"))
        page.context.close()

        # --- retry actually works -------------------------------------------
        MODE.update(how="recovers", attempt=0)
        page = fresh()
        run_turn(page, "Try this one twice.")
        if not page.is_visible("#retry"):
            browser.close()
            sys.exit("FAIL: no Try again offered on the recoverable failure")
        page.click("#retry")
        page.wait_for_function("() => !document.getElementById('send').disabled",
                               timeout=30000)
        page.wait_for_timeout(500)
        mine = page.eval_on_selector_all(
            ".msg.me", "els => els.map(e => e.innerText.trim())")
        bots = page.eval_on_selector_all(
            ".msg.bot", "els => els.map(e => e.innerText.trim())")
        _p(f"\nretry     : resent {mine!r}")
        _p(f"            {len(bots)} agent message(s) after the retry")
        if mine.count("Try this one twice.") != 2:
            failures.append(f"Try again did not resend the original message: {mine}")
        if not any("Done." in b for b in bots):
            failures.append("the retried run did not complete")

        # --- the read API going away ----------------------------------------
        # A dot changing colour was the entire signal, which is nothing at all to
        # someone who cannot distinguish the two colours.
        # From here on a console error is the app behaving correctly -- we are cutting
        # the API off on purpose, and refresh() is supposed to log and show offline.
        # Only crashes BEFORE this line are defects.
        unexpected = list(crashes)
        page.route("**/api/challenges/**", lambda r: r.abort())
        page.wait_for_timeout(5000)
        live = page.inner_text("#live").strip()
        label = page.eval_on_selector("#live", "e => e.nextElementSibling.innerText.trim()")
        _p(f"offline   : indicator={live!r} label={label!r}")
        if label.lower() != "offline":
            failures.append(f"the connection indicator still reads {label!r} with the "
                            "read API down")
        page.screenshot(path=str(ROOT / "_err_offline.png"))
        browser.close()

    _p(f"\npage errors: {unexpected if unexpected else 'none'}")
    if unexpected:
        failures.append(f"JavaScript threw during a failure path: {unexpected[:3]}")

    if failures:
        _p("\n--- FAILURES ---")
        for f in failures:
            _p(" * " + f)
        sys.exit(1)

    _p("\nfailures explain themselves and offer a way forward. wrote _err_*.png")


if __name__ == "__main__":
    main()
