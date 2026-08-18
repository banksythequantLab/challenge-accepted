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
    # A single_turn agent is not a transfer target -- ADK exposes it to its parent as a
    # TOOL and runs it in an isolated sub-branch, `cartographer@call_<n>`. It is still
    # OFFERED its parent as a transfer target though, and taking that offer is a trap:
    # the Warden then resumes INSIDE this sub-branch instead of after it, and so does
    # everything it does next. Measured on the deployed service:
    #
    #   branch=cartographer@call_636196.forge_workers.toolwright_0   <- 5 specs, 2 tools
    #   branch=cartographer@call_630649.forge_workers.toolwright_0   <- 6 specs, 1 tool
    #   branch=forge_workers.toolwright_0                            <- 8 specs, 8 tools
    #
    # When the tool call closes, the frame closes, and FORGE dies underneath it with no
    # error anywhere: workers make their second model call, never reach
    # `after_agent_callback`, and the loop never dispatches another batch. That is the
    # same signature blamed on worker concurrency earlier -- halving the batch changed
    # the odds, not the mechanism.
    #
    # So: finish and return, like the tool this already is. Control goes back to the
    # Warden by the tool returning, which is the path that does not nest.
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    tools=[save_goal_graph, write_journal],
)
