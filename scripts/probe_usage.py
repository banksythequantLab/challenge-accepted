"""Dump raw usage_metadata per event, to check the token accounting.

live_walk.py reported output=20,000 exactly, which is too round to trust. Either a cap
is being hit or the accounting is wrong. Gemini 3.x charges thinking tokens as output,
and they are reported separately from candidates_token_count -- if we only sum
candidates we are UNDER-counting cost, not over.

    python scripts\\probe_usage.py
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

from google.adk.agents import LlmAgent, SequentialAgent  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from challenge_accepted import config  # noqa: E402

FIELDS = [
    "prompt_token_count",
    "candidates_token_count",
    "thoughts_token_count",
    "tool_use_prompt_token_count",
    "cached_content_token_count",
    "total_token_count",
]


async def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("No GOOGLE_API_KEY.")

    agent = LlmAgent(
        name="usage_probe",
        model=config.MODEL_REASONING,
        description="probe",
        instruction="Answer thoroughly and think it through.",
        mode="single_turn",
    )
    wrapped = SequentialAgent(name="wrap", description="w", sub_agents=[agent])
    runner = InMemoryRunner(agent=wrapped, app_name="usage_probe")
    session = await runner.session_service.create_session(
        app_name="usage_probe", user_id="u", state={}
    )

    totals = {f: 0 for f in FIELDS}
    events = 0
    async for event in runner.run_async(
        user_id="u", session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(
            text="Explain in 3 short paragraphs why dependency graphs beat flat "
                 "to-do lists for planning work.")]),
    ):
        if getattr(event, "partial", False):
            continue
        usage = getattr(event, "usage_metadata", None)
        if not usage:
            continue
        events += 1
        row = {f: getattr(usage, f, None) for f in FIELDS}
        print(f"  event {events}: {row}")
        for f in FIELDS:
            totals[f] += row[f] or 0

    print(f"\n  events with usage: {events}")
    print(f"  summed: {totals}")
    print("\n  NOTE: thinking tokens bill as OUTPUT on Gemini 3.x. If")
    print("  thoughts_token_count is non-zero, live_walk.py under-reports cost by")
    print("  exactly that much, because it sums candidates_token_count only.")


if __name__ == "__main__":
    asyncio.run(main())
