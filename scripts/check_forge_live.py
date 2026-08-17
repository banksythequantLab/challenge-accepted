"""Does FORGE build tools on the DEPLOYED service, and does it build all of them?

Every earlier check of the money shot ran against a local server on a `GOOGLE_API_KEY`.
That is a different Gemini mode from production, and the difference silently killed
every Toolwright on every deployed revision for weeks:

    ValueError: include_server_side_tool_invocations parameter is only supported in
    Gemini Developer API mode, not in Gemini Enterprise Agent Platform mode.

Nothing looked wrong. The deploy was green, health was green, the graph drew, the
journal filled and the FORGE rail animated -- around `tools: []`. The only way to see it
was to count tools on the deployed service, which nothing did.

So this counts them, and it counts the *specs* too. Tools alone cannot tell you whether
FORGE built everything it meant to or gave up after one: for that you need what the
Quartermaster asked for, which lives in session state because an agent with an
`output_schema` gets no tools and cannot journal what it decided.

    python scripts\\check_forge_live.py https://challengeaccepted.app

Exit 0 only if at least one tool was built AND every spec that asked for a tool got one.

**Signed in since Google Sign-In shipped.** For several revisions this check could not
reach production at all -- every call came back 401 and the only honest thing to say
about FORGE on the deployed service was that nothing was measuring it. That gap cost
real time: the returning `ValueError` about code-part ids was eventually found by
reading a stream trace line by line, and this is the check whose entire job is to catch
exactly that. It now mints a throwaway identity the same way the other live checks do.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

APP = "challenge_accepted"
DEFAULT_URL = "https://challengeaccepted.app"

#: The signed-in identity everything below runs as. `None` on a deployment with auth
#: off, which keeps this check usable against a local server.
_UID: str | None = None
_TOKEN: tuple[float, str] = (0.0, "")


def _auth() -> dict[str, str]:
    """A bearer token for the test identity, re-minted before it can expire.

    A full FORGE run is four turns of up to ten minutes each, and a Firebase ID token
    lasts an hour. Minting once at the top would let a long run die on a 401 in the
    final turn -- which reads exactly like the product failing, and is the kind of
    false accusation this file already has a comment apologising for.
    """
    global _TOKEN
    if _UID is None:
        return {}
    minted, token = _TOKEN
    if not token or time.time() - minted > 1800:
        from testauth import mint

        token = mint(_UID)
        _TOKEN = (time.time(), token)
    return {"Authorization": "Bearer " + token}

TURNS = [
    "I want to run a 10k in under 55 minutes by Christmas.",
    "I run about 3k twice a week at a slow pace. I have never trained properly.",
    "I can train four evenings a week, about 45 minutes each. Success is crossing the "
    "line at the Christmas Eve park 10k under 55 minutes.",
    "That's everything -- accept the challenge, draw me the map, and build the tools.",
]


def _json(url, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json", **_auth()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # A 401/403 is the check failing to sign in, not FORGE failing to build. Say
        # which, out loud -- a silent auth failure here would look like an empty run.
        detail = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit(
            f"\n{e.code} from {url}\n{detail}\n"
            "This is the CHECK being refused, not the product misbehaving.") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _say(base, user, sid, text):
    raw = _json(base + "/run_sse", {
        "app_name": APP, "user_id": user, "session_id": sid,
        "new_message": {"role": "user", "parts": [{"text": text}]},
        "streaming": False,
    })
    authors = []
    if isinstance(raw, str):
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                for p in (ev.get("content") or {}).get("parts") or []:
                    if p.get("functionCall"):
                        authors.append(f"{ev.get('author','?')}->"
                                       f"{p['functionCall'].get('name')}")
                    if p.get("executableCode"):
                        authors.append(f"{ev.get('author','?')}->code")
    return authors


def _specs_from_state(state):
    """Every ToolSpec the Quartermaster produced, wherever FORGE parked it.

    The first version of this walked one level and missed `tool_specs`, which is a dict
    of `{"specs": [...]}` rather than a bare list. So on the run that finally worked it
    reported `specs asked: 0` and PASSED -- with nothing to compare against. A check
    that can pass by failing to look is worse than no check, so `main` now treats an
    unreadable spec set as a failure rather than a pass.
    """
    specs = []

    def _harvest(value):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return
        if isinstance(value, dict):
            if value.get("node_id") or value.get("name"):
                specs.append(value)
            else:
                for nested in value.values():
                    _harvest(nested)
        elif isinstance(value, list):
            for item in value:
                _harvest(item)

    for key, value in (state or {}).items():
        if "spec" in key or "forge" in key:
            _harvest(value)
    # A spec can be parked in a slot AND in the queue at once; count each node once.
    seen, unique = set(), []
    for s in specs:
        node = s.get("node_id") or s.get("name")
        if node not in seen:
            seen.add(node)
            unique.append(s)
    return unique


def main(base: str) -> int:
    global _UID
    base = base.rstrip("/")
    health = _json(base + "/api/healthz", timeout=60)
    print(f"target : {base}")
    print(f"health : store={health.get('store')} memory={health.get('memory')} "
          f"auth={health.get('auth')}")

    # The identity has to BE the path user. authgate.py refuses any request whose
    # `/users/<id>/` segment disagrees with the verified token, which is the whole
    # point of it -- so the check signs in as the user it is about to act as rather
    # than inventing a name and bolting a token on beside it.
    if health.get("auth") == "required":
        from testauth import PREFIX

        _UID = PREFIX + "forge_" + uuid.uuid4().hex[:6]
        _auth()  # mint now, so a credentials problem fails here and not mid-run
        print(f"signed in as {_UID}\n")
    else:
        _UID = None
        print("auth off on this deployment -- running unauthenticated\n")
    user = _UID or f"forge_{uuid.uuid4().hex[:8]}"
    sid = "s_" + uuid.uuid4().hex[:10]

    _json(f"{base}/apps/{APP}/users/{user}/sessions",
          {"session_id": sid, "state": {"user_id": user, "group_id": f"grp_{user}"}},
          timeout=60)

    calls = []
    for text in TURNS:
        print(f">>> {text[:74]}")
        t = time.perf_counter()
        got = _say(base, user, sid, text)
        calls += got
        print(f"    {time.perf_counter() - t:5.0f}s  {len(got)} tool calls")

    forge_calls = [c for c in calls if "toolwright" in c.lower()]
    print("\n--- what the workers did ---")
    for c in forge_calls[:24]:
        print(f"   {c}")
    if not forge_calls:
        print("   (nothing -- no Toolwright made a call)")

    session = _json(f"{base}/apps/{APP}/users/{user}/sessions/{sid}", timeout=60)
    specs = _specs_from_state(session.get("state") if isinstance(session, dict) else {})

    cid = (session.get("state") or {}).get("challenge_id") if isinstance(session, dict) else None
    tools = []
    if cid:
        dash = _json(f"{base}/api/challenges/{cid}/dashboard", timeout=60)
        raw = dash.get("tools")
        tools = (raw.get("tools") if isinstance(raw, dict) else raw) or []

    wanted = [s for s in specs if s.get("needed") is not False]
    print(f"\nchallenge   : {cid}")
    print(f"specs asked : {len(wanted)}")
    print(f"tools built : {len(tools)}")
    for t in tools:
        print(f"   - {t.get('type')} | {(t.get('name') or '')[:58]}")

    if not tools:
        print("\nFAIL: the deployed service built nothing. This is the money shot.")
        return 1
    if not wanted:
        print("\nFAIL: tools exist but no specs were readable, so completeness is "
              "unverified. Passing here would mean passing because we did not look.")
        return 1
    if len(tools) < len(wanted):
        print(f"\nFAIL: {len(wanted) - len(tools)} spec(s) never became a tool. FORGE "
              "started and did not finish -- which looks identical to success from "
              "the dashboard.")
        return 1
    print("\nPASS: every spec that asked for a tool got one, on the deployed service.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
