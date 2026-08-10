"""Warden -- the root agent.

`root_agent` is the name ADK looks for. `adk web` from the repo root will find this
package and expose it.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from . import config, prompts
from .services.tools import read_challenge_state, write_journal
from .sub_agents import archivist, cartographer, coach, forge, interviewer, referee
from .sub_agents.scout import scout_tool

root_agent = LlmAgent(
    name="warden",
    model=config.MODEL_REASONING,
    description=(
        "Challenge Accepted. Interviews the user about a goal, decomposes it into a "
        "dependency graph of micro-tasks, builds the tools each step needs, then "
        "coaches them through it -- taking notes into shared group memory throughout."
    ),
    instruction=prompts.WARDEN,
    sub_agents=[interviewer, cartographer, forge, coach, referee, archivist],
    tools=[scout_tool, read_challenge_state, write_journal],
)

__all__ = ["root_agent"]
