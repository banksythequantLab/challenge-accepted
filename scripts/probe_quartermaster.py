"""How many of a 10-node graph does the Quartermaster actually ask tools for?

A live run built 4 tools for 10 nodes, and FORGE_WORKERS is 4 -- suspicious. The loop
was cleared by tests/test_forge_loop.py (it drains 10 specs in batches of 4/4/2), so
the remaining explanation is that Quartermaster only marked 4 nodes as needing a tool.
The prompt tells it "roughly a third of nodes should get no tool", so 4/10 would be
slightly aggressive pruning but within intent. This measures it.

    python scripts\\probe_quartermaster.py

One model call. Cheap.
"""

from __future__ import annotations

import asyncio
import json
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

from google.adk.agents import SequentialAgent  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from google.adk.agents import LlmAgent  # noqa: E402

from challenge_accepted import config, prompts  # noqa: E402
from challenge_accepted.sub_agents.forge import ToolSpecList  # noqa: E402


def fresh_quartermaster() -> LlmAgent:
    """A new instance, not the module singleton.

    An ADK agent may have only one parent, and the module-level `quartermaster` is
    already attached to `forge`. Reusing it here raises:
    "Agent `quartermaster` already has a parent agent".
    """
    return LlmAgent(
        name="quartermaster",
        model=config.MODEL_REASONING,
        description="Decides, per node, which tool type would make it trivial.",
        instruction=prompts.QUARTERMASTER,
        mode="single_turn",
        output_schema=ToolSpecList,
        output_key="tool_specs",
    )

NODES = [
    ("adk-spike", "Prove a minimal ADK agent responds via the API"),
    ("frontend-shell", "Next.js app shell with routing and auth stub"),
    ("demo-video-script", "Write the 4-minute demo script beat by beat"),
    ("backend-api-wiring", "Expose the agent over an SSE endpoint"),
    ("frontend-backend-integration", "Stream agent events into the UI"),
    ("deployment-setup", "Deploy to Cloud Run behind the domain"),
    ("e2e-testing-polishing", "Walk the whole flow and fix what breaks"),
    ("demo-recording", "Record the screen capture for the video"),
    ("demo-editing", "Cut the recording to under 4 minutes"),
    ("devpost-submission", "Fill in the Devpost form and submit"),
]


async def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("No GOOGLE_API_KEY.")

    graph = "\n".join(f"- {nid}: {desc}" for nid, desc in NODES)
    prompt = (
        "Here is the saved goal graph for 'Launch Challenge Accepted at the hackathon "
        "by Aug 31'. The user is a solo developer with 3 hours a night on weekdays, "
        "full days at weekends, who has never used Google ADK before and has run out "
        "of time on the demo video at two previous hackathons.\n\n"
        f"{graph}\n\nEmit one ToolSpec per node."
    )

    wrapped = SequentialAgent(name="qm_probe", description="probe",
                              sub_agents=[fresh_quartermaster()])
    runner = InMemoryRunner(agent=wrapped, app_name="qm_probe")
    session = await runner.session_service.create_session(
        app_name="qm_probe", user_id="u", state={}
    )
    async for _ in runner.run_async(
        user_id="u", session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
    ):
        pass

    final = await runner.session_service.get_session(
        app_name="qm_probe", user_id="u", session_id=session.id
    )
    raw = final.state.get("tool_specs")
    if isinstance(raw, str):
        raw = json.loads(raw)
    specs = (raw or {}).get("specs", [])

    needed = [s for s in specs if s.get("needed")]
    print(f"\nnodes in graph : {len(NODES)}")
    print(f"specs emitted  : {len(specs)}")
    print(f"needed=true    : {len(needed)}")
    print(f"needed=false   : {len(specs) - len(needed)}\n")
    for s in specs:
        mark = "TOOL" if s.get("needed") else "  --"
        print(f"  {mark}  {s.get('node_id'):<32} {s.get('tool_type') or ''}")

    missing = {n for n, _ in NODES} - {s.get("node_id") for s in specs}
    if missing:
        print(f"\n!!! nodes with NO spec at all: {sorted(missing)}")


if __name__ == "__main__":
    asyncio.run(main())
