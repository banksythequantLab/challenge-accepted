"""Warden -- the root agent.

`root_agent` is the name ADK looks for. `adk web` from the repo root will find this
package and expose it.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from . import config, prompts
from .services.memory import preload_memory
from .services.store import store
from .services.tools import read_challenge_state, remember_group_fact, write_journal
from . import vertex_compat
from .sub_agents import archivist, cartographer, coach, forge, interviewer
from .sub_agents.scout import scout_tool


def warden_instruction(ctx: ReadonlyContext) -> str:
    """WARDEN, plus a hard statement of fact when a challenge is already in flight.

    The prompt has always carried a rule saying a teammate joining an in-flight
    challenge does not get interviewed. It did not hold. Driven through two real
    browsers, the second user said "the permit office only issues permits on Tuesdays"
    and Warden handed them to the Interviewer, which asked them what observable outcome
    they wanted -- for a challenge whose charter was saved and whose map had eleven
    steps on the screen in front of them.

    A rule competing with seven other rules loses. A fact does not. ADK resolves an
    InstructionProvider on every turn, so when state carries a challenge id we look up
    what is actually true and say it, rather than asking the model to remember to check.
    """
    cid = ctx.state.get("challenge_id")
    if not cid:
        return prompts.WARDEN

    challenge = store.get("challenges", str(cid)) or {}
    charter = challenge.get("charter") or {}
    nodes = [n for n in store.list_nodes(str(cid)) if n.get("status") != "superseded"]
    if not charter or not nodes:
        # Mid-ACCEPT or mid-MAP. The normal phase rules are exactly right.
        return prompts.WARDEN

    return prompts.WARDEN + "\n\n" + prompts.in_flight_banner(
        title=charter.get("title") or charter.get("outcome") or "this challenge",
        outcome=charter.get("outcome", ""),
        total=len(nodes),
        done=len([n for n in nodes if n.get("status") == "done"]),
    )


root_agent = LlmAgent(
    name="warden",
    model=config.MODEL_REASONING,
    description=(
        "Challenge Accepted. Interviews the user about a goal, decomposes it into a "
        "dependency graph of micro-tasks, builds the tools each step needs, then "
        "coaches them through it -- taking notes into shared group memory throughout."
    ),
    instruction=warden_instruction,
    # Referee is deliberately NOT here. It reaches the Coach as an AgentTool instead --
    # as a sibling it caused an infinite delegation loop live. See sub_agents/referee.py.
    sub_agents=[interviewer, cartographer, forge, coach, archivist],
    # `remember_group_fact` is here, not only on Archivist and Coach, because Warden
    # was caught telling a teammate "I've recorded that into our shared group memory"
    # on a turn where it held no tool capable of doing so. Nothing was written. An
    # agent that can claim a thing must be able to do the thing -- the alternative is
    # a product whose central promise is a sentence it made up.
    # `preload_memory` is not model-callable. It hooks `process_llm_request`, searches
    # Vertex AI Memory Bank with whatever the user just typed, and appends any hits as
    # dynamic instructions -- so it costs nothing against the tool-count ceiling that
    # bit us before. It is wired unconditionally, including locally and under test,
    # because ADK's implementation swallows every exception out of `search_memory`:
    # with no memory service it logs and returns. Wiring it only in production would
    # mean the agent we test is not the agent we ship, which is the shape of most of
    # the bugs in the Known issues section.
    tools=[scout_tool, read_challenge_state, write_journal, remember_group_fact,
           preload_memory],
)

#: Vertex rejects the `id` on code parts, and the ROOT agent is the one that trips it:
#: it runs unbranched, so ADK's per-agent history filter lets it see the Toolwrights'
#: `executableCode` events from inside FORGE. Attaching the guard to the whole tree is
#: what makes that safe -- see vertex_compat for the traceback that proved it.
#: Asserted, not assumed: a silent no-op here restores the bug exactly.
_GUARDED = vertex_compat.install(root_agent)
assert _GUARDED >= 6, f"the Vertex id guard reached only {_GUARDED} agents"

__all__ = ["root_agent", "warden_instruction"]
