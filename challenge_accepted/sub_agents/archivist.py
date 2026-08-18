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
    # Same trap as the Cartographer, and the comment there has the measurements. A
    # single_turn agent runs as a TOOL in its own sub-branch; if it transfers back to
    # the Warden instead of returning, the Warden resumes inside that sub-branch and
    # everything it starts next dies when the tool call closes. This one has not been
    # caught doing it -- it is closed off because the shape is identical and the
    # failure is silent, not because there is a second traceback.
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    tools=[read_challenge_state, write_journal, remember_group_fact],
)
