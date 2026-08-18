"""A single-turn sub-agent must return, not transfer back.

ADK exposes a `mode="single_turn"` sub-agent to its parent as a TOOL and runs it in an
isolated sub-branch, `<name>@call_<n>`. It is nonetheless offered its parent as a
transfer target, and taking that offer is the bug: the parent resumes INSIDE the
child's frame rather than after it, and everything it starts from there dies when the
tool call closes. Measured on the deployed service:

    branch=cartographer@call_636196.forge_workers.toolwright_0   -> 5 specs, 2 tools
    branch=cartographer@call_630649.forge_workers.toolwright_0   -> 6 specs, 1 tool
    branch=forge_workers.toolwright_0                            -> 8 specs, 8 tools

No error, no traceback: the workers make their second model call and never reach
`after_agent_callback`. That is the same signature that was blamed on worker
concurrency, which means halving the batch changed the odds and not the mechanism.

This is a one-line setting on an agent nobody looks at twice, its absence is silent,
and the last time this class of bug regressed it cost days. So it is pinned.
"""

from __future__ import annotations

import pytest

from challenge_accepted.agent import root_agent


def _by_name(name):
    for sub in root_agent.sub_agents:
        if sub.name == name:
            return sub
    raise AssertionError(f"{name} is no longer a sub-agent of {root_agent.name}")


@pytest.mark.parametrize("name", ["cartographer", "archivist"])
def test_single_turn_sub_agents_cannot_transfer_back(name):
    agent = _by_name(name)
    assert getattr(agent, "mode", None) == "single_turn", (
        f"{name} is no longer single_turn -- re-check whether this guard still applies "
        f"rather than deleting it")
    assert agent.disallow_transfer_to_parent is True
    assert agent.disallow_transfer_to_peers is True


def test_the_conversational_sub_agents_are_left_alone():
    """Not a blanket rule. `mode="task"` agents (Interviewer, Coach) run in a sub-branch
    and hand control back through `finish_task`, which returns cleanly -- the live
    trace shows the Warden resuming FLAT after the Interviewer. Locking those down
    would be cargo-culting a fix onto a path that never had the problem."""
    for name in ("interviewer", "coach"):
        agent = _by_name(name)
        assert getattr(agent, "mode", None) == "task", name
        assert agent.disallow_transfer_to_parent is False, (
            f"{name} runs in task mode and returns through finish_task; nothing "
            f"measured says it needs this")


def test_the_root_still_owns_the_handoffs():
    """The Warden has to be able to reach every phase, or the fix above would have
    swapped a silent stall for a silent dead end."""
    names = {s.name for s in root_agent.sub_agents}
    assert {"interviewer", "cartographer", "forge", "coach", "archivist"} <= names
