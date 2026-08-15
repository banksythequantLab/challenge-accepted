"""Drive the real chat UI in a real browser against a stubbed backend.

The Quartermaster carries an `output_schema`, so its whole turn is a machine payload
for the Dispatcher. app.html was rendering any text from any author as a speech
bubble, so a user who asked for a plan was shown the wire format:

    QUARTERMASTER {   "specs": [     {       "node_id": "audit-34-sites", ...

check_render.mjs proves the two helpers work. This proves the STREAM LOOP uses them --
including the case that has no successor event to trigger the flush, which is the one
a unit test cannot see.

    python scripts\\check_chat_render.py

Exits non-zero on the first failure. No cloud, no keys, no deploy.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_HTML = ROOT / "challenge_accepted" / "static" / "app.html"

SPECS = {
    "specs": [
        {"node_id": "audit-34-sites", "needed": True, "tool_type": "checklist",
         "name": "Site Tier Audit & Prioritization Checklist"},
        {"node_id": "outreach", "needed": True, "tool_type": "tracker",
         "name": "Outreach Tracker"},
        {"node_id": "think", "needed": False, "name": "Reflect on positioning"},
    ]
}

# Turn 1 ends on prose, so the flush is triggered by the next author.
# Turn 2 ends on the payload, so only the end-of-stream flush can save it.
TURN_1 = [
    ("warden", "Right. 34 sites, $25k MRR. Let us break that down."),
    ("quartermaster", json.dumps(SPECS, indent=2)),
    ("dispatcher", "Handing three specs to the Forge."),
]
TURN_2 = [
    ("warden", "Understood."),
    ("quartermaster", json.dumps(SPECS, indent=2)),
]


def sse(turn) -> bytes:
    out = []
    for author, text in turn:
        ev = {"author": author, "content": {"parts": [{"text": text}]}}
        out.append(f"data: {json.dumps(ev)}\n\n")
    return "".join(out).encode()


class Stub(BaseHTTPRequestHandler):
    turn = [0]

    def log_message(self, *a):  # keep the run readable
        pass

    def _send(self, body: bytes, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/app"):
            return self._send(APP_HTML.read_bytes(), "text/html; charset=utf-8")
        if self.path.startswith("/api/challenges"):
            return self._send(b'{"challenges": []}')
        if "/sessions/" in self.path:
            return self._send(b'{"id": "s_test", "state": {}}')
        return self._send(b"{}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/run_sse":
            self.turn[0] += 1
            body = sse(TURN_1 if self.turn[0] == 1 else TURN_2)
            return self._send(body, "text/event-stream")
        if self.path.endswith("/sessions"):
            return self._send(b'{"id": "s_test", "state": {}}')
        return self._send(b"{}")


def main() -> int:
    from playwright.sync_api import sync_playwright

    srv = HTTPServer(("127.0.0.1", 0), Stub)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    failures: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.on("pageerror", lambda e: failures.append(f"pageerror: {e}"))
            page.goto(f"http://127.0.0.1:{port}/app", wait_until="networkidle")

            for label, expect_last in (("ends on prose", False), ("ends on payload", True)):
                page.fill("#input", "get me to $25k MRR across 34 sites")
                page.click("#send")
                page.wait_for_function(
                    "() => !document.getElementById('send').disabled", timeout=20000)
                page.wait_for_timeout(300)

                bodies = page.eval_on_selector_all(
                    "#chatlog .msg.bot .body", "els => els.map(e => e.innerText)")
                blob = "\n".join(bodies)

                if re.search(r'node_id|"needed"|"tool_type"', blob):
                    failures.append(f"[{label}] raw payload is still on screen:\n"
                                    f"{blob[:400]}")
                if "Planned 2 tools" not in blob:
                    failures.append(f"[{label}] no spec summary rendered. Bubbles:\n"
                                    f"{blob[:400]}")
                if "Site Tier Audit & Prioritization Checklist" not in blob:
                    failures.append(f"[{label}] summary lost the tool names")
                if "judged 1 step fine without one" not in blob:
                    failures.append(f"[{label}] summary lost the skipped spec")
                if not expect_last and "Handing three specs to the Forge." not in blob:
                    failures.append(f"[{label}] a normal prose turn went missing")

                shots = ROOT / "_walk"
                shots.mkdir(exist_ok=True)
                page.screenshot(path=str(shots / f"render_{label.replace(' ', '_')}.png"))
                print(f"{label:<16} -> {len(bodies)} bot bubble(s)")

            browser.close()
    finally:
        srv.shutdown()

    if failures:
        for f in failures:
            print("FAIL: " + f)
        return 1
    print("\nPASS -- the wire format never reaches the chat, on both flush paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
