"""Structural invariants of the agent tree.

Every assertion here corresponds to a failure that actually happened live and cost a
run. None of them need an API key.
"""

from __future__ import annotations

from google.adk.tools.agent_tool import AgentTool

from challenge_accepted.agent import root_agent
from challenge_accepted.sub_agents import coach, referee, referee_tool, scout, scout_tool


def _agent_tools(agent) -> list[AgentTool]:
    return [t for t in (agent.tools or []) if isinstance(t, AgentTool)]


def test_agent_tools_are_chat_mode():
    """An AgentTool runs its agent as a ROOT agent, and ADK rejects a non-chat root:
    "LlmAgent as root agent must have mode='chat'". Broke the Referee live; Scout had
    the same defect sitting latent because it was never invoked."""
    for tool in (referee_tool, scout_tool):
        mode = getattr(tool.agent, "mode", None)
        assert mode in (None, "chat"), (
            f"{tool.agent.name} is wrapped as an AgentTool but has mode={mode!r}; "
            f"it will raise the moment something calls it."
        )


def test_referee_is_a_coach_tool_not_a_warden_sibling():
    """As a Warden sibling the Referee deadlocked: the Coach could not reach it, bounced
    to Warden, and Warden re-delegated 25 times in one turn with no result."""
    assert "referee" not in [a.name for a in root_agent.sub_agents]
    assert "referee" in [t.agent.name for t in _agent_tools(coach)]


def test_task_mode_agents_have_no_sub_agents():
    """ADK requires task-mode agents to be leaves."""
    def walk(agent):
        if getattr(agent, "mode", None) == "task":
            assert not (agent.sub_agents or []), (
                f"{agent.name} is mode='task' but has sub-agents"
            )
        for sub in (agent.sub_agents or []):
            walk(sub)

    walk(root_agent)


def test_every_agent_has_a_description():
    """Delegation is chosen by the parent LLM from sub-agent descriptions. A blank one
    makes an agent effectively unreachable."""
    def walk(agent):
        assert (agent.description or "").strip(), f"{agent.name} has no description"
        for sub in (agent.sub_agents or []):
            walk(sub)

    walk(root_agent)
    for a in (referee, scout):
        assert (a.description or "").strip()


def test_models_meet_the_hackathon_floor():
    """Rules require "Gemini 3.5 or newer". gemini-3.1-pro-preview does NOT qualify."""
    seen: set[str] = set()

    def walk(agent):
        model = getattr(agent, "model", None)
        if isinstance(model, str) and model:
            seen.add(model)
        for sub in (agent.sub_agents or []):
            walk(sub)

    walk(root_agent)
    seen.add(referee.model)
    seen.add(scout.model)
    for model in seen:
        assert model.startswith(("gemini-3.5", "gemini-3.6")), (
            f"{model} does not satisfy 'Gemini 3.5 or newer'"
        )
