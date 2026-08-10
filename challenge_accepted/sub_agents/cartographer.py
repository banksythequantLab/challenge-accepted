"""MAP phase -- turns the charter into a dependency graph of micro-tasks."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from .. import config, prompts
from ..services.tools import save_goal_graph, write_journal

cartographer = LlmAgent(
    name="cartographer",
    model=config.MODEL_REASONING,
    description=(
        "Decomposes a saved charter into a DAG of 8-20 micro-tasks with dependency "
        "edges and acceptance criteria. Use after the charter is saved, and again "
        "after the interview is re-opened."
    ),
    instruction=prompts.CARTOGRAPHER,
    mode="single_turn",
    tools=[save_goal_graph, write_journal],
)
