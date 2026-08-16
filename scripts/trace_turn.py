"""Record every raw /run_sse event of a real conversation against a deployed service.

walkthrough.py showed a browser turn ending immediately after the Warden invoked the
Cartographer -- no reply, no nodes, no error on screen. The UI only renders text and
functionCalls, so an event carrying an error, or a functionResponse carrying a failure,
is invisible there. This prints EVERYTHING the server sent, in order, with the response
payloads, so the silence has somewhere to hide.

    python scripts\\trace_turn.py https://challengeaccepted.app

Exit 1 if any event carries an error or any tool response looks like a failure.
"""

from __future__ import annotations

import json
import sys
import uuid

import requests

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

DEFAULT_URL = "https://challengeaccepted.app"
APP_NAME = "challenge_accepted"

#: Filled in by main() once the service says auth is required. Empty against a local
#: server with CA_AUTH=off, so this script runs in both worlds unchanged.
AUTH: dict[str, str] = {}


def _auth_for(base: str, uid: str) -> None:
    """Sign in as a throwaway test identity if the deployment demands one."""
    global AUTH
    health = requests.get(f"{base}/api/healthz", timeout=60).json()
    if health.get("auth") != "required":
        _p("auth: off on this deployment -- running unauthenticated\n")
        return
    from testauth import mint

    AUTH = {"Authorization": "Bearer " + mint(uid)}
    _p(f"auth: signed in as {uid}\n")

TURNS = [
    "I want to run a 10k in under 55 minutes by Christmas.",
    "I run about 3k twice a week at a slow pace. I have never trained properly.",
    "I can train four evenings a week for about 45 minutes. It is an official "
    "organised park 10k on Christmas Eve, and I am doing it alone.",
    "That's everything I know -- please accept the challenge, draw the map and "
    "build the tools.",
]


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def short(v, n: int = 220) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + f" ... (+{len(s) - n} chars)"


def check_dashboard(data: dict) -> list[str]:
    """Read the dashboard the way the browser reads it.

    Guessing at these shapes is how this script first reported "0 nodes, 1 tool" on a
    run that had in fact saved 10 nodes and 6 tools: `/dashboard` returns the graph
    under `graph.nodes` (react-flow shaped, so a node's tool lives in `data`) and the
    tools under `tools.tools`. A check that invents the response shape does not test
    the product, it tests the guess.
    """
    bad: list[str] = []
    counts = (data.get("summary") or {}).get("counts") or {}
    nodes = (data.get("graph") or {}).get("nodes") or []
    tools = (data.get("tools") or {}).get("tools") or []
    armed = [n for n in nodes if (n.get("data") or {}).get("tools")]
    _p(f"dashboard: {len(nodes)} node(s), {len(tools)} tool(s), "
       f"{len(armed)} node(s) showing an Open-tool button")
    _p(f"summary counts: {counts}")
    for t in tools:
        _p(f"  - {t.get('node_id')} | {t.get('name')}"
           f"{' [DEGRADED]' if t.get('degraded') else ''}")

    # The Party pane's whole promise. A teammate opening the invite link reads this.
    party_facts = (data.get("summary") or {}).get("group_facts") or []
    _p(f"party notebook: {len(party_facts)} fact(s)")
    for f in party_facts:
        _p(f"  * {f}")
    if not party_facts:
        bad.append("the party notebook is empty -- a teammate arrives at "
                   "'Nothing learned yet' on a fully planned challenge")

    if not nodes:
        bad.append("the challenge exists but its map has no nodes")
    if not tools:
        bad.append("the challenge exists but no tools were forged")
    if counts.get("nodes") != len(nodes):
        bad.append(f"summary says {counts.get('nodes')} nodes, graph carries {len(nodes)}")
    if counts.get("tools") != len(tools):
        bad.append(f"summary says {counts.get('tools')} tools, list carries {len(tools)}")
    # A tool nobody can reach is not a tool. This is the claim the UI makes.
    if tools and not armed:
        bad.append(f"{len(tools)} tool(s) exist but no node exposes one -- "
                   f"nothing is openable from the map")
    return bad


def main() -> int:
    args = [a for a in sys.argv[1:]]
    # `--dashboard <challenge_id>` re-reads an existing challenge without spending
    # four minutes of model time re-running the conversation.
    if "--dashboard" in args:
        i = args.index("--dashboard")
        cid = args[i + 1]
        base = (args[0] if i > 0 else DEFAULT_URL).rstrip("/")
        r = requests.get(f"{base}/api/challenges/{cid}/dashboard", timeout=180)
        r.raise_for_status()
        bad = check_dashboard(r.json())
        for x in bad:
            _p(" * " + x)
        return 1 if bad else 0

    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL).rstrip("/")
    # The user id has to BE the signed-in uid now: the gate refuses a session whose
    # path names anyone else, which is the whole point of it.
    user = "ca_test_" + uuid.uuid4().hex[:8]
    session = "s_" + uuid.uuid4().hex[:8]
    _auth_for(base, user)

    r = requests.post(
        f"{base}/apps/{APP_NAME}/users/{user}/sessions",
        headers=AUTH,
        json={"session_id": session,
              "state": {"user_id": user, "group_id": "grp_" + user}},
        timeout=60)
    r.raise_for_status()
    session = r.json().get("id", session)
    _p(f"session {session} as {user}\n")

    problems: list[str] = []

    for i, text in enumerate(TURNS, 1):
        _p(f"===== turn {i}: {text[:60]}...")
        with requests.post(
            f"{base}/run_sse",
            headers=AUTH,
            json={"appName": APP_NAME, "userId": user, "sessionId": session,
                  "streaming": False,
                  "newMessage": {"role": "user", "parts": [{"text": text}]}},
            stream=True, timeout=900,
        ) as resp:
            if resp.status_code != 200:
                problems.append(f"turn {i}: HTTP {resp.status_code} {resp.text[:200]}")
                continue
            events = 0
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except Exception:
                    continue
                events += 1
                who = ev.get("author", "?")

                # ADK puts turn-level failures here. Nothing in the UI reads them.
                for key in ("errorCode", "errorMessage", "error_code", "error_message"):
                    if ev.get(key):
                        problems.append(f"turn {i} {who}: {key}={ev[key]}")
                        _p(f"  !! {who}: {key} = {ev[key]}")

                for p in (ev.get("content") or {}).get("parts") or []:
                    if p.get("text"):
                        _p(f"  {who} text: {short(p['text'])}")
                    if p.get("functionCall"):
                        fc = p["functionCall"]
                        _p(f"  {who} call: {fc.get('name')} {short(fc.get('args'), 120)}")
                    if p.get("functionResponse"):
                        fr = p["functionResponse"]
                        body = fr.get("response")
                        _p(f"  {who} resp: {fr.get('name')} -> {short(body)}")
                        blob = json.dumps(body, default=str).lower()
                        if any(w in blob for w in
                               ('"error"', 'traceback', 'exception', 'failed')):
                            problems.append(
                                f"turn {i} {who}: {fr.get('name')} responded "
                                f"{short(body, 300)}")
                    if p.get("executableCode"):
                        _p(f"  {who} code: {len(p['executableCode'].get('code',''))} chars")
                    if p.get("codeExecutionResult"):
                        _p(f"  {who} ran : "
                           f"{p['codeExecutionResult'].get('outcome')}")
            _p(f"  ({events} events)\n")
            if not events:
                problems.append(f"turn {i}: the stream carried no events at all")

    # What did the run actually leave behind?
    d = requests.get(f"{base}/apps/{APP_NAME}/users/{user}/sessions/{session}",
                     headers=AUTH, timeout=60)
    state = d.json().get("state", {}) if d.ok else {}
    cid = state.get("challenge_id")
    _p(f"challenge_id in session state: {cid or 'NONE'}")
    if not cid:
        problems.append("no challenge_id was ever written to session state")
    else:
        dash = requests.get(f"{base}/api/challenges/{cid}/dashboard",
                            headers=AUTH, timeout=120)
        if not dash.ok:
            problems.append(f"dashboard HTTP {dash.status_code}: {dash.text[:200]}")
        else:
            problems += check_dashboard(dash.json())

    if problems:
        _p("\n--- problems ---")
        for x in problems:
            _p(" * " + x)
        return 1
    _p("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
