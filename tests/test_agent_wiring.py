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


def test_the_referee_can_record_the_refusals_it_makes():
    """A NOT_MET leaves no other mark anywhere in the system.

    COMPLETE closes a node and the graph shows it. NOT_MET changes nothing visible --
    the node stays exactly as it was -- so unless the Referee writes it down, a
    teammate opening the challenge tomorrow sees a step nobody has touched when the
    truth is it was attempted twice and refused for the same missing number both
    times. For most of this build the Referee held every tool it needed to SAY no and
    none to record having said it, and nothing here noticed because a missing journal
    entry looks exactly like a step nobody tried.
    """
    from challenge_accepted.sub_agents.referee import referee

    names = [getattr(t, "name", getattr(t, "__name__", "")) for t in referee.tools]
    assert "write_journal" in names, f"the Referee cannot journal anything: {names}"


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


#: Non-Gemini models allowed in the tree, each with the reason it is there. The rules
#: make Gemini 3.5+ mandatory; they do not make it exclusive, and they pay a bonus for
#: additional Google models. An allowlist rather than a blanket "anything non-Gemini is
#: fine" -- the point of this test is to catch a model nobody meant to ship, and
#: "it isn't Gemini" is exactly what an accidental one would look like.
ADDITIONAL_GOOGLE_MODELS = {
    "gemma-4-26b-a4b-it-maas": "Archivist. Open model, Vertex MaaS, +0.2 bonus.",
}


def _models_in_the_tree() -> set[str]:
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
    return seen


def test_a_qualifying_gemini_is_actually_in_use():
    """The mandatory technology, quoted:

        "Gemini 3.5 or newer accessed through Gemini API or Vertex AI"

    This is a Stage One gate -- missing it is elimination before anything is scored --
    so what it checks is that a qualifying model is genuinely wired into the tree, not
    that one is mentioned somewhere in the config.
    """
    qualifying = [m for m in _models_in_the_tree()
                  if m.startswith(("gemini-3.5", "gemini-3.6"))]
    assert qualifying, (
        "no Gemini 3.5+ model is wired into the agent tree; the entry fails the "
        f"mandatory-technology gate. Models found: {sorted(_models_in_the_tree())}")


def test_every_other_model_is_one_we_chose_on_purpose():
    """The rules make Gemini 3.5+ mandatory, not exclusive -- and pay up to +0.6 for
    additional Google models. So a non-Gemini model is allowed, but only a named one.

    Without the allowlist this test would have to be deleted the day Gemma landed, and
    deleting it is how `gemini-3.1-pro-preview` gets back in: it reads as newer than
    3.5 to a human skimming a version string, and it does not qualify.
    """
    for model in _models_in_the_tree():
        if model.startswith(("gemini-3.5", "gemini-3.6")):
            continue
        assert model in ADDITIONAL_GOOGLE_MODELS, (
            f"{model} is neither 'Gemini 3.5 or newer' nor a declared additional "
            f"model. Declared: {sorted(ADDITIONAL_GOOGLE_MODELS)}")


def test_the_agents_that_decide_things_are_on_gemini():
    """The open model is scoped to transcription, and that scoping is the argument.

    Gemma on the Archivist is defensible because the Archivist only records. The same
    move on the Coach, the Cartographer or a Toolwright would be a different claim
    entirely -- so this fails if the open model spreads.
    """
    from challenge_accepted.sub_agents.archivist import archivist
    from challenge_accepted.sub_agents.cartographer import cartographer
    from challenge_accepted.sub_agents.interviewer import interviewer

    for agent in (root_agent, coach, cartographer, interviewer, scout, referee):
        assert agent.model.startswith(("gemini-3.5", "gemini-3.6")), (
            f"{agent.name} is on {agent.model}")
    assert archivist.model in ADDITIONAL_GOOGLE_MODELS
