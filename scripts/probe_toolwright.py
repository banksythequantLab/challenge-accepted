"""Run ONE Toolwright worker in isolation and unwrap the real exception.

The ParallelAgent wraps worker failures in an ExceptionGroup whose sub-exceptions never
reach the console, so a broken worker looks like "unhandled errors in a TaskGroup".
This runs a single worker directly and recursively unwraps whatever it raises.

    python scripts\\probe_toolwright.py
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

# NB: `from challenge_accepted.sub_agents import forge` gives you the SequentialAgent
# object, not the module -- the package __init__ re-exports a name that shadows it.
from challenge_accepted.sub_agents.forge import SLOT_PREFIX, _worker  # noqa: E402

SPEC = {
    "node_id": "demo-video-editing",
    "needed": True,
    "tool_type": "calculator",
    "name": "Video Cut Budget",
    "purpose": "Work out how many seconds each beat can take to land under 4 minutes.",
    "inputs": ["beat names", "target total seconds"],
    "outputs": ["seconds per beat"],
    "smoke_test": "Given 8 beats and a 225 second target, output should total 225.",
}


def unwrap(exc: BaseException, depth: int = 0) -> None:
    pad = "  " * depth
    print(f"{pad}{type(exc).__name__}: {str(exc)[:500]}")
    for sub in getattr(exc, "exceptions", []) or []:
        unwrap(sub, depth + 1)
    if exc.__cause__ is not None:
        print(f"{pad}caused by:")
        unwrap(exc.__cause__, depth + 1)


async def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("No GOOGLE_API_KEY.")

    worker = _worker(0)
    print(f"agent      : {worker.name}")
    print(f"model      : {worker.model}")
    print(f"executor   : {type(worker.code_executor).__name__}")
    print(f"tools      : {[getattr(t, '__name__', getattr(t, 'name', t)) for t in worker.tools]}\n")

    # A single_turn LlmAgent cannot be a root agent ("must have mode='chat'"), so wrap
    # it the same way the real pipeline does.
    from google.adk.agents import SequentialAgent

    wrapped = SequentialAgent(name="probe_wrap", description="probe", sub_agents=[worker])
    runner = InMemoryRunner(agent=wrapped, app_name="probe")
    session = await runner.session_service.create_session(
        app_name="probe",
        user_id="u",
        state={"user_id": "u", "challenge_id": "chal_probe",
               f"{SLOT_PREFIX}0": SPEC},
    )
    try:
        async for event in runner.run_async(
            user_id="u", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="Build it.")]),
        ):
            if getattr(event, "partial", False):
                continue
            for part in (getattr(getattr(event, "content", None), "parts", None) or []):
                if getattr(part, "text", None):
                    print(f"  {part.text.strip()[:300]}")
                if getattr(part, "function_call", None):
                    print(f"  -> CALL {part.function_call.name}")
                if getattr(part, "executable_code", None):
                    print(f"  -- CODE {len(part.executable_code.code or '')} chars")
                if getattr(part, "code_execution_result", None):
                    print(f"  -- EXEC {part.code_execution_result.outcome}")
    except BaseException as exc:  # noqa: BLE001
        print("\n!!! RAISED:\n")
        unwrap(exc)


if __name__ == "__main__":
    asyncio.run(main())
