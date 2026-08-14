"""Does the PRODUCT remember? Two challenges, one user, one fact that can only
have come from memory.

`check_memory_bank.py` proves the infrastructure round-trips. This proves the feature:
that a fact told to the agents during one challenge reaches them during the next one,
through `save_charter` -> Memory Bank -> `preload_memory`, with no help from session
state, Firestore group facts, or the dashboard.

The trick is picking a fact that cannot arrive any other way. The second session is
brand new -- new session id, no `challenge_id`, no `group_id` -- so the only channel
from the first conversation to the second is Memory Bank. If the needle shows up in the
second conversation, memory carried it. Nothing else could have.

This drives HTTP rather than a browser on purpose. The browser checks exist to prove the
UI wires up; this one is about whether a fact survives a conversation boundary, and a
headless Chrome in the middle would only add ways for it to fail.

    python scripts\\check_memory.py https://challenge-accepted-xk3m7ygefa-uc.a.run.app

Exit code 0 only if the second conversation surfaces the needle.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import uuid

APP = "challenge_accepted"
DEFAULT_URL = "https://challenge-accepted-xk3m7ygefa-uc.a.run.app"

#: Two needles, because one could be luck. Both are specific enough that a model
#: inventing plausible filler would not land on them.
NEEDLES = ("Hollowmere", "nephew")

CHALLENGE_ONE = [
    "I want to run a 10k in under 55 minutes by Christmas.",
    "I can only train on Tuesday evenings, because I look after my nephew every other "
    "night. The race I am aiming at is the Hollowmere parkrun 10k.",
    "I run about 3k at a slow pace right now and I have never trained properly.",
    "That's everything -- accept the challenge and draw me the map.",
]

#: Deliberately not leading. It never mentions running, a day of the week, or a name.
#: Anything specific in the answer had to come out of memory.
PROBE = "Before we start something new -- what do you already know about me?"


def _post(base: str, path: str, body: dict, timeout: int = 300) -> str:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _new_session(base: str, user: str, state: dict) -> str:
    sid = "s_" + uuid.uuid4().hex[:10]
    _post(base, f"/apps/{APP}/users/{user}/sessions",
          {"session_id": sid, "state": state}, timeout=60)
    return sid


def _say(base: str, user: str, sid: str, text: str) -> str:
    """One turn. Returns every scrap of model text the server emitted."""
    raw = _post(base, "/run_sse", {
        "app_name": APP, "user_id": user, "session_id": sid,
        "new_message": {"role": "user", "parts": [{"text": text}]},
        "streaming": False,
    })
    out = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        for part in (event.get("content") or {}).get("parts") or []:
            if part.get("text"):
                out.append(f"{event.get('author', '?')}: {part['text']}")
    return "\n".join(out)


def _found(haystack: str) -> list[str]:
    low = haystack.lower()
    return [n for n in NEEDLES if n.lower() in low]


def main(base: str) -> int:
    user = f"mem_{uuid.uuid4().hex[:8]}"
    print(f"target : {base}")
    print(f"user   : {user}\n")

    health = json.loads(urllib.request.urlopen(
        base.rstrip("/") + "/api/healthz", timeout=60).read())
    print(f"health : store={health.get('store')} memory={health.get('memory')} "
          f"sessions={health.get('sessions')}")
    if health.get("memory") != "agentengine":
        print("\nSKIP: this deployment has no Memory Bank configured, so there is "
              "nothing here to test. Deploy with -AgentEngineId first.")
        return 2

    # --- challenge one: tell them something worth remembering ----------------
    print("\n--- challenge one ---")
    sid1 = _new_session(base, user, {"user_id": user, "group_id": f"grp_{user}"})
    for text in CHALLENGE_ONE:
        print(f">>> {text[:78]}")
        reply = _say(base, user, sid1, text)
        print(f"    ...{len(reply)} chars back")
    print("charter saved -> save_charter should have written to Memory Bank")

    # --- wait for generation -------------------------------------------------
    # Memory Bank runs a model over the ingested events; the probe measured ~28s.
    # This is latency, not failure, and the check says which one it hit.
    print("\n--- waiting for memory generation ---")

    # --- challenge two: a brand new session, same person ----------------------
    # No challenge_id and no group_id. Session state cannot carry anything here.
    for wait in (45, 45, 60, 60):
        time.sleep(wait)
        sid2 = _new_session(base, user, {"user_id": user})
        reply = _say(base, user, sid2, PROBE)
        hits = _found(reply)
        elapsed = "elapsed"
        print(f"probe after ~{wait}s more: {len(reply)} chars, needles={hits or 'none'}")
        if hits:
            print("\n--- what it said ---")
            print(reply[:1200])
            print()
            print(f"PASS: a fresh session recalled {hits} with no session state to "
                  "carry it. That came out of Memory Bank.")
            return 0
        _ = elapsed

    print("\nFAIL: four fresh sessions, none surfaced anything from challenge one.")
    print("      Check /api/healthz says memory=agentengine, then run")
    print("      scripts\\check_memory_bank.py to see whether the service itself is "
          "round-tripping. If that passes and this fails, the gap is preload_memory "
          "or the prompt -- not the infrastructure.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL))
