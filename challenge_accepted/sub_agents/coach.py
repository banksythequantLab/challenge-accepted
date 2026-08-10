"""CLIMB phase -- guides the user through one node at a time.

Coach runs in `mode="task"` rather than `chat`. Chat mode returns to the parent only
via an explicit transfer_to_agent and is not parallel-safe; task mode auto-returns via
finish_task(), which is what makes the CLIMB -> ACCEPT re-open path work cleanly.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from .. import config, prompts
from ..services.tools import read_challenge_state, write_journal

coach = LlmAgent(
    name="coach",
    model=config.MODEL_REASONING,
    description=(
        "Guides the user step by step through the goal graph, presenting one ready "
        "node at a time along with the tool built for it. Use after FORGE completes."
    ),
    instruction=prompts.COACH,
    mode="task",
    tools=[read_challenge_state, write_journal],
)
