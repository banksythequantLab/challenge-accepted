"""Two users, one challenge: does what Derek learns reach Dana?

This is the demo beat that sells the Collaborative Partner track -- two windows, one
goal graph, and the second person's Coach opening with something the first person
discovered. It is also the last piece of backend behaviour never exercised.

Sequence:
  1. Derek runs the pipeline: charter -> graph -> tools.
  2. Derek hits a blocker. That should land as a group fact.
  3. Dana opens the SAME challenge in a fresh session, same group, different user id.
  4. Dana asks what to work on.

Pass condition: Dana's Coach references Derek's constraint without being told, and does
not hand Dana a node Derek already finished.

    python scripts\\live_group.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from challenge_accepted.agent import root_agent  # noqa: E402
from challenge_accepted.services.store import store  # noqa: E402
from live_walk import TURNS as SETUP_TURNS, _describe  # noqa: E402

APP = "challenge_accepted"
GROUP = "grp_team"

DEREK_CLIMB = [
    "What should I work on first?",
    "I could not finish that one. Cloud Run needs billing enabled on the project and I "
    "do not have admin on that Google account. Also our whole team is blocked on that "
    "same account, so nobody can deploy to GCP.",
]

DANA_TURNS = [
    "Hi, I'm Dana, joining Derek on this. What should I pick up?",
]

TOKENS = {"prompt": 0, "candidates": 0, "thoughts": 0}


async def send(runner, user: str, session_id: str, text: str, show: bool) -> str:
    """Send one turn; return the concatenated assistant text."""
    said: list[str] = []
    last = None
    async for event in runner.run_async(
        user_id=user, session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        if getattr(event, "partial", False):
            continue
        usage = getattr(event, "usage_metadata", None)
        if usage:
            TOKENS["prompt"] += getattr(usage, "prompt_token_count", 0) or 0
            TOKENS["candidates"] += getattr(usage, "candidates_token_count", 0) or 0
            TOKENS["thoughts"] += getattr(usage, "thoughts_token_count", 0) or 0
        for part in (getattr(getattr(event, "content", None), "parts", None) or []):
            if getattr(part, "text", None):
                said.append(part.text)
        if not show:
            continue
        lines = _describe(event)
        if not lines:
            continue
        if event.author != last:
            print(f"\n[{event.author}]")
            last = event.author
        for line in lines:
            print(line)
    return "\n".join(said)


async def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("No GOOGLE_API_KEY.")

    runner = InMemoryRunner(agent=root_agent, app_name=APP)

    # --- Derek ---------------------------------------------------------------
    derek = await runner.session_service.create_session(
        app_name=APP, user_id="derek", state={"user_id": "derek", "group_id": GROUP}
    )
    print("### Derek: running ACCEPT -> MAP -> FORGE (output suppressed) ...")
    for turn in SETUP_TURNS:
        await send(runner, "derek", derek.id, turn, show=False)

    mid = await runner.session_service.get_session(
        app_name=APP, user_id="derek", session_id=derek.id
    )
    cid = str(mid.state.get("challenge_id") or "")
    print(f"### challenge={cid} nodes={len(store.list_nodes(cid))} "
          f"tools={len(store.list_tools(cid))}")

    for i, turn in enumerate(DEREK_CLIMB, 1):
        print(f"\n{'=' * 78}\nDEREK {i}: {turn}\n{'=' * 78}")
        await send(runner, "derek", derek.id, turn, show=True)

    facts = (store.get("groups", GROUP) or {}).get("shared_facts", [])
    print(f"\n### group facts after Derek: {len(facts)}")
    for f in facts:
        print(f"      - {f}")

    # --- Dana ----------------------------------------------------------------
    # A fresh session, a different user, the SAME challenge and group. This is exactly
    # what the app does when a teammate opens the shared challenge.
    dana = await runner.session_service.create_session(
        app_name=APP, user_id="dana",
        state={"user_id": "dana", "group_id": GROUP, "challenge_id": cid},
    )
    print(f"\n{'=' * 78}\nDANA (new session, same challenge): {DANA_TURNS[0]}\n{'=' * 78}")
    reply = await send(runner, "dana", dana.id, DANA_TURNS[0], show=True)

    # --- Did the knowledge cross? -------------------------------------------
    print(f"\n{'=' * 78}\nGROUP RESULT\n{'=' * 78}")
    lowered = reply.lower()
    signals = {
        "mentions the blocker": any(
            k in lowered for k in ("billing", "cloud run", "admin", "gcp")
        ),
        "names Derek": "derek" in lowered,
        "mentions deploy constraint or alternative": any(
            k in lowered for k in ("vercel", "deploy", "hosting", "blocked")
        ),
    }
    for label, hit in signals.items():
        print(f"  [{'x' if hit else ' '}] {label}")

    done_ids = {n["id"] for n in store.list_nodes(cid) if n.get("status") == "done"}
    offered_a_finished_node = any(nid in lowered for nid in done_ids)
    print(f"  [{'!' if offered_a_finished_node else ' '}] "
          f"offered Dana a node Derek already finished (should be blank)")
    print(f"\n  group facts : {len(facts)}")
    print(f"  nodes done  : {len(done_ids)}")

    billed = TOKENS["candidates"] + TOKENS["thoughts"]
    print(f"\n  tokens: prompt={TOKENS['prompt']:,} billed_output={billed:,}")
    print(f"  cost: ${TOKENS['prompt'] / 1e6 * 1.50 + billed / 1e6 * 7.50:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
