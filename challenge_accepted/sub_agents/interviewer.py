"""ACCEPT phase -- the clarifying-question engine.

`mode="task"` is the load-bearing choice: it lets the agent ask the user questions
mid-execution and hand control back to Warden automatically via finish_task().
Task-mode agents are leaf-level (no sub_agents) and are disabled inside graph-based
workflows in ADK Python v2.x -- which is why the phase pipeline here is built from
agent transfer plus Sequential/Parallel/Loop agents, not a workflow graph.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from .. import config, prompts
from ..services.memory import preload_memory
from ..services.tools import read_challenge_state, save_charter, write_journal

interviewer = LlmAgent(
    name="interviewer",
    model=config.MODEL_REASONING,
    description=(
        "Interviews the user with clarifying questions until the challenge is specific "
        "enough to plan. Produces and saves the charter. Use at the start, and again "
        "whenever a new constraint invalidates the plan."
    ),
    instruction=prompts.INTERVIEWER,
    mode="task",
    # `preload_memory` earns its place here more than anywhere else: the cheapest
    # clarifying question is the one we do not have to ask because the user answered
    # it during a previous challenge. It is not model-callable -- it hooks the LLM
    # request and injects any hits as dynamic instructions.
    tools=[read_challenge_state, save_charter, write_journal, preload_memory],
)
