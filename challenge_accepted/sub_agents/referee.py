"""Evidence check and feedback capture.

Runs on the cheap model tier -- this is judgement against a written criterion, not
open-ended reasoning, and it fires on every single node.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from .. import config, prompts
from ..services.tools import complete_node, read_challenge_state, record_feedback

referee = LlmAgent(
    name="referee",
    model=config.MODEL_CHEAP,
    description=(
        "Checks a node's evidence against its acceptance criterion, closes it when met, "
        "and captures the user's thumbs up/down plus reason. Use when the user reports "
        "finishing a step."
    ),
    instruction=prompts.REFEREE,
    mode="task",
    tools=[read_challenge_state, complete_node, record_feedback],
)
