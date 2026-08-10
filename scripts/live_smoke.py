"""Live smoke test -- drives the real agent tree against real Gemini.

Not a unit test. This is the thing you run to find out whether the prompts work,
because nothing in tests/ ever calls a model.

    python scripts\\live_smoke.py "I want to run a half marathon in October"

Prints every event: which agent spoke, which tool it called, what it said.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from challenge_accepted.agent import root_agent  # noqa: E402

APP = "challenge_accepted"
USER = "derek"


def _describe(event) -> list[str]:
    """Flatten one event into readable lines."""
    lines = []
    content = getattr(event, "content", None)
    for part in (getattr(content, "parts", None) or []):
        if getattr(part, "text", None):
            lines.append(f"    {part.text.strip()}")
        if getattr(part, "function_call", None):
            fc = part.function_call
            args = ", ".join(f"{k}={str(v)[:60]}" for k, v in (fc.args or {}).items())
            lines.append(f"    -> CALL {fc.name}({args})")
        if getattr(part, "function_response", None):
            fr = part.function_response
            lines.append(f"    <- {fr.name}: {str(fr.response)[:160]}")
    return lines


async def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("No GOOGLE_API_KEY. Put it in .env or the environment.")

    challenge = " ".join(sys.argv[1:]) or "I want to run a half marathon in October"
    print(f"\n=== CHALLENGE: {challenge}\n")

    runner = InMemoryRunner(agent=root_agent, app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id=USER, state={"user_id": USER, "group_id": "grp_derek"}
    )

    last_author = None
    async for event in runner.run_async(
        user_id=USER,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=challenge)]),
    ):
        if getattr(event, "partial", False):
            continue
        lines = _describe(event)
        if not lines:
            continue
        if event.author != last_author:
            print(f"\n[{event.author}]")
            last_author = event.author
        for line in lines:
            print(line)

    final = await runner.session_service.get_session(
        app_name=APP, user_id=USER, session_id=session.id
    )
    print("\n=== SESSION STATE KEYS ===")
    for key in sorted(final.state):
        print(f"  {key} = {str(final.state[key])[:110]}")

    from challenge_accepted.services.store import store

    cid = final.state.get("challenge_id")
    if cid:
        print("\n=== JOURNAL ===")
        for entry in store.list_journal(str(cid)):
            print(f"  [{entry['actor']}/{entry['kind']}] {entry['text']}")
        print(f"\n=== NODES: {len(store.list_nodes(str(cid)))} ===")
    else:
        print("\n(no challenge_id -- charter was never saved)")


if __name__ == "__main__":
    asyncio.run(main())
