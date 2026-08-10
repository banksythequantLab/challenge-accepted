"""Grounded research.

Scout is wrapped as an AgentTool by whoever needs it. That is not stylistic: a built-in
tool such as google_search excludes every other tool on the same agent, so Scout must
live alone and be reached through AgentTool.

Cost note: Google Search grounding is 5,000 free requests/month, then $14 per 1,000.
That is a real line item at scale, so Scout is invoked deliberately, never by default.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool

from .. import config, prompts

scout = LlmAgent(
    name="scout",
    model=config.MODEL_REASONING,
    description="Answers a single factual question using grounded Google Search.",
    instruction=prompts.SCOUT,
    mode="single_turn",
    tools=[google_search],
)

#: Use this, not `scout`, when adding research to another agent.
scout_tool = AgentTool(agent=scout)
