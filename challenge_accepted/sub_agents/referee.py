"""Evidence check and feedback capture.

Runs on the cheap model tier -- this is judgement against a written criterion, not
open-ended reasoning, and it fires on every single node.

WHY THIS IS AN AgentTool AND NOT A SIBLING SUB-AGENT
----------------------------------------------------
It used to be a `mode="task"` sub-agent of Warden. Live, that produced an infinite
loop: the Coach was told to "transfer to referee", but a sibling is not reachable from
the Coach, so it transferred up to Warden instead. Warden's instruction said nothing
about a Referee, so it improvised -- calling `referee(...)` 25 times in one turn, each
call returning nothing, each failure prompting another attempt.

Wrapping it as an AgentTool makes the interaction a plain function call with a return
value: Coach calls it, gets a verdict back, and keeps control of the conversation. It
is `single_turn` because an AgentTool cannot pause to ask the user a question -- if the
evidence is ambiguous the Referee returns the question and the Coach asks it.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from .. import config, prompts
from ..services.tools import (
    complete_node,
    read_challenge_state,
    record_feedback,
    write_journal,
)

referee = LlmAgent(
    name="referee",
    model=config.MODEL_CHEAP,
    description=(
        "Checks a node's evidence against its acceptance criterion, closes it when met, "
        "and records the user's thumbs up/down. Returns a verdict; never talks to the "
        "user directly."
    ),
    instruction=prompts.REFEREE,
    # MUST be "chat". An AgentTool runs its agent as a ROOT agent in a nested
    # invocation, and ADK rejects a non-chat root:
    #   ValueError: LlmAgent as root agent must have mode='chat', but got 'single_turn'.
    # It still behaves as a single shot here -- it has no parent to transfer to, and it
    # returns its text as the tool result.
    mode="chat",
    # `write_journal` was missing here for most of the build, and its absence was
    # invisible: the Referee held every tool it needed to SAY no and none to RECORD
    # having said it. A refused node looks identical to an untouched one.
    tools=[read_challenge_state, complete_node, record_feedback, write_journal],
)

#: Give this to the Coach, not the Warden.
referee_tool = AgentTool(agent=referee)
