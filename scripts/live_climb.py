"""Drive the CLIMB phase: Coach guides, Referee verifies, feedback is captured.

live_walk.py stops once tools are built. CLIMB is the half of the Collaborative Partner
brief that actually gets judged -- "guide the user step-by-step" and "have a clear way
to capture feedback, so it constantly adapts". None of it had ever run.

The last scripted turn deliberately fails a node for a reason nobody knew about, to see
whether the system does the honest thing: record a blocker, save a durable group fact,
and re-open rather than improvise around it.

    python scripts\\live_climb.py

Costs real tokens (~$1). Reuses live_walk's ACCEPT/MAP/FORGE turns to get there.
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
USER = "derek"

#: Turn 2 is deliberately THOROUGH. An earlier version said only "I saved a screenshot
#: of the JSON response" and the Referee correctly returned NOT_MET, because the
#: acceptance criterion asked for logs across several sample goals. That strictness is
#: the product working, not a bug -- so the script now supplies evidence that actually
#: meets a criterion of that shape.
CLIMB_TURNS = [
    "Good. What should I work on first?",
    "Done. I ran three sample goals through the backend with curl and captured the "
    "logs -- all three returned 200 OK with generated tool output in the response "
    "body. The logs are committed to the repo under logs/spike/.",
    "Thumbs up on that checklist, it caught the auth step I would have skipped.",
    "What is next?",
    "I could not finish that one. It turns out Cloud Run needs billing enabled on the "
    "project, and I do not have admin on that Google account.",
]

TOKENS = {"prompt": 0, "candidates": 0, "thoughts": 0}


async def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("No GOOGLE_API_KEY.")

    runner = InMemoryRunner(agent=root_agent, app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id=USER, state={"user_id": USER, "group_id": "grp_derek"}
    )

    async def send(turn: str, show: bool) -> None:
        last = None
        async for event in runner.run_async(
            user_id=USER, session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=turn)]),
        ):
            if getattr(event, "partial", False):
                continue
            usage = getattr(event, "usage_metadata", None)
            if usage:
                TOKENS["prompt"] += getattr(usage, "prompt_token_count", 0) or 0
                TOKENS["candidates"] += getattr(usage, "candidates_token_count", 0) or 0
                TOKENS["thoughts"] += getattr(usage, "thoughts_token_count", 0) or 0
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

    print("### Setting up (ACCEPT -> MAP -> FORGE), output suppressed ...")
    for turn in SETUP_TURNS:
        await send(turn, show=False)

    mid = await runner.session_service.get_session(
        app_name=APP, user_id=USER, session_id=session.id
    )
    cid = str(mid.state.get("challenge_id") or "")
    print(f"### setup done: challenge={cid} "
          f"nodes={len(store.list_nodes(cid))} tools={len(store.list_tools(cid))}")

    for i, turn in enumerate(CLIMB_TURNS, 1):
        print(f"\n{'=' * 78}\nCLIMB {i}: {turn}\n{'=' * 78}")
        try:
            await send(turn, show=True)
        except Exception as exc:  # noqa: BLE001
            print(f"\n!!! CLIMB TURN {i} FAILED: {type(exc).__name__}: {str(exc)[:400]}")
            break

    print(f"\n{'=' * 78}\nCLIMB RESULT\n{'=' * 78}")
    nodes = store.list_nodes(cid)
    done = [n for n in nodes if n.get("status") == "done"]
    print(f"  nodes done   : {len(done)} / {len(nodes)}")
    for n in nodes:
        if n.get("status") != "todo":
            print(f"      {n.get('status'):<8} {n.get('id')}  evidence={n.get('evidence')}")

    fb = store.list_feedback(cid)
    print(f"  feedback     : {len(fb)}")
    for f in fb:
        print(f"      {f.get('verdict')} on {f.get('target_type')}={f.get('target_id')}"
              f"  reason={str(f.get('reason'))[:80]}")

    group = store.get("groups", "grp_derek") or {}
    facts = group.get("shared_facts", [])
    print(f"  group facts  : {len(facts)}")
    for fact in facts:
        print(f"      - {fact}")

    journal = store.list_journal(cid)
    print(f"  journal      : {len(journal)} entries; last 8:")
    for j in journal[-8:]:
        print(f"      [{j.get('actor')}/{j.get('kind')}] {str(j.get('text'))[:100]}")

    billed = TOKENS["candidates"] + TOKENS["thoughts"]
    cost = TOKENS["prompt"] / 1e6 * 1.50 + billed / 1e6 * 7.50
    print(f"\n  tokens: prompt={TOKENS['prompt']:,} billed_output={billed:,}")
    print(f"  cost: ${cost:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
