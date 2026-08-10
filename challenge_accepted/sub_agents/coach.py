"""CLIMB phase -- guides the user through one node at a time.

Coach runs in `mode="task"` rather than `chat`. Chat mode returns to the parent only
via an explicit transfer_to_agent and is not parallel-safe; task mode auto-returns via
finish_task(), which is what makes the CLIMB -> ACCEPT re-open path work.

The Referee arrives here as an AgentTool rather than as a sibling agent. See
referee.py for why -- the sibling arrangement deadlocked live.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from .. import config, prompts
from ..services.tools import (
    read_challenge_state,
    record_feedback,
    remember_group_fact,
    write_journal,
)
from .referee import referee_tool

coach = LlmAgent(
    name="coach",
    model=config.MODEL_REASONING,
    description=(
        "Guides the user step by step through the goal graph, presenting one ready "
        "node at a time along with the tool built for it, and verifying completions "
        "via the referee tool. Use after FORGE completes."
    ),
    instruction=prompts.COACH,
    mode="task",
    # The Coach owns the conversation, so it owns feedback capture and durable facts.
    # Routing a thumbs-up through the Referee failed live: the Referee judged it as
    # completion evidence, returned NOT_MET, and never recorded anything.
    tools=[
        read_challenge_state,
        write_journal,
        record_feedback,
        remember_group_fact,
        referee_tool,
    ],
)
