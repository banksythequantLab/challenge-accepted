"""Cross-cutting note-taker.

"Takes notes" is in the track brief verbatim, so it is a first-class agent here rather
than a logging side effect. Archivist writes to two places: the Firestore journal, which
the user reads live, and Vertex AI Memory Bank, which the other agents read before their
next turn.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from .. import config, prompts
from ..services.tools import read_challenge_state, remember_group_fact, write_journal

archivist = LlmAgent(
    name="archivist",
    model=config.MODEL_CHEAP,
    description=(
        "Records what was learned: a visible journal entry, plus durable group facts "
        "that other teammates and future sessions should inherit. Use after any turn "
        "where something was decided or discovered."
    ),
    instruction=prompts.ARCHIVIST,
    mode="single_turn",
    tools=[read_challenge_state, write_journal, remember_group_fact],
)
