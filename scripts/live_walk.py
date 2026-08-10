"""Scripted multi-turn walk through the whole pipeline, against real Gemini.

live_smoke.py sends one turn and stops at the Interviewer's first question. This drives
a full scripted conversation so the run actually reaches MAP and FORGE -- which is where
the interesting failures live (Warden -> forge transfer, Quartermaster's output_schema,
Toolwright fan-out and code execution).

    python scripts\\live_walk.py

Costs real tokens. Prints a token total at the end so you can calibrate unit economics.
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
from challenge_accepted.services.store import store  # noqa: E402

APP = "challenge_accepted"
USER = "derek"

TURNS = [
    "I want to launch MicroGoals at the hackathon by Aug 31.",
    "A deployed URL where a judge types a goal and watches agents build them a working "
    "tool, plus a 4-minute demo video submitted on Devpost.",
    "Hard deadline Aug 31, 5pm PDT. I get about 3 hours a night on weekdays and full "
    "days on weekends.",
    "My constraint is time, and I have never used Google ADK before. Budget is fine.",
    "I already built the agent backend, but I have never shipped a Next.js front end "
    "this fast. At my last two hackathons I ran out of time on the demo video.",
    "Just me. Solo submission.",
    "Yes, that is right. Go ahead and map it out.",
    "Looks good. Build whatever tools those steps need.",
]

# Thinking tokens bill as OUTPUT on Gemini 3.x and are reported separately from
# candidates_token_count. Summing candidates alone under-reports cost by ~3x -- measured
# 725 thinking vs 251 visible on a single short call. Track both.
TOKENS = {"prompt": 0, "candidates": 0, "thoughts": 0, "cached": 0}

PRICE_IN_PER_M = 1.50   # gemini-3.6-flash
PRICE_OUT_PER_M = 7.50


def _describe(event) -> list[str]:
    lines = []
    for part in (getattr(getattr(event, "content", None), "parts", None) or []):
        if getattr(part, "text", None):
            text = part.text.strip()
            if text:
                lines.append(f"    {text[:400]}")
        if getattr(part, "function_call", None):
            fc = part.function_call
            args = ", ".join(f"{k}={str(v)[:70]}" for k, v in (fc.args or {}).items())
            lines.append(f"    -> CALL {fc.name}({args[:220]})")
        if getattr(part, "function_response", None):
            fr = part.function_response
            lines.append(f"    <- {fr.name}: {str(fr.response)[:180]}")
        if getattr(part, "executable_code", None):
            code = part.executable_code.code or ""
            lines.append(f"    -- CODE ({len(code)} chars): {code.splitlines()[0][:90] if code else ''}")
        if getattr(part, "code_execution_result", None):
            res = part.code_execution_result
            lines.append(f"    -- EXEC {res.outcome}: {str(res.output)[:160]}")
    return lines


async def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("No GOOGLE_API_KEY.")

    runner = InMemoryRunner(agent=root_agent, app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id=USER, state={"user_id": USER, "group_id": "grp_derek"}
    )

    for i, turn in enumerate(TURNS, 1):
        print(f"\n{'=' * 78}\nUSER {i}: {turn}\n{'=' * 78}")
        last_author = None
        try:
            async for event in runner.run_async(
                user_id=USER,
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=turn)]),
            ):
                if getattr(event, "partial", False):
                    continue
                usage = getattr(event, "usage_metadata", None)
                if usage:
                    TOKENS["prompt"] += getattr(usage, "prompt_token_count", 0) or 0
                    TOKENS["candidates"] += getattr(usage, "candidates_token_count", 0) or 0
                    TOKENS["thoughts"] += getattr(usage, "thoughts_token_count", 0) or 0
                    TOKENS["cached"] += getattr(usage, "cached_content_token_count", 0) or 0
                lines = _describe(event)
                if not lines:
                    continue
                if event.author != last_author:
                    print(f"\n[{event.author}]")
                    last_author = event.author
                for line in lines:
                    print(line)
        except Exception as exc:  # noqa: BLE001
            print(f"\n!!! TURN {i} FAILED: {type(exc).__name__}: {str(exc)[:400]}")
            break

    final = await runner.session_service.get_session(
        app_name=APP, user_id=USER, session_id=session.id
    )
    cid = final.state.get("challenge_id")

    print(f"\n{'=' * 78}\nRESULT\n{'=' * 78}")
    print(f"  challenge_id : {cid}")
    print(f"  state keys   : {sorted(k for k in final.state)}")
    if cid:
        nodes = store.list_nodes(str(cid))
        tools = store.list_tools(str(cid))
        print(f"  nodes        : {len(nodes)}")
        for n in nodes[:25]:
            print(f"      - {n.get('id'):<34} deps={n.get('depends_on')}")
        print(f"  tools built  : {len(tools)}")
        for t in tools:
            flag = "ok" if t.get("smoke_test_passed") else "DEGRADED"
            print(f"      - {t.get('name')} [{t.get('type')}] {flag} node={t.get('node_id')}")
        print(f"  journal      : {len(store.list_journal(str(cid)))} entries")
    billed_out = TOKENS["candidates"] + TOKENS["thoughts"]
    cost = (TOKENS["prompt"] / 1e6 * PRICE_IN_PER_M
            + billed_out / 1e6 * PRICE_OUT_PER_M)
    ratio = (TOKENS["thoughts"] / TOKENS["candidates"]) if TOKENS["candidates"] else 0

    print(f"\n  prompt tokens     : {TOKENS['prompt']:,}")
    print(f"  visible output    : {TOKENS['candidates']:,}")
    print(f"  thinking tokens   : {TOKENS['thoughts']:,}  ({ratio:.1f}x visible)")
    print(f"  cached            : {TOKENS['cached']:,}")
    print(f"  BILLED output     : {billed_out:,}  (candidates + thoughts)")
    print(f"\n  cost at 3.6-flash rates: ${cost:.4f} per challenge")
    if cost:
        print(f"  break-even at $29/seat/mo: {29 / cost:.0f} challenges/user/month")


if __name__ == "__main__":
    asyncio.run(main())
