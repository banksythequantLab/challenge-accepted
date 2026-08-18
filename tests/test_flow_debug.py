"""The trace that exists because an absence is not evidence.

One run in two stopped after `save_charter` with no error, no traceback and no log
line -- the Warden had finished the turn alone and nothing said so. These pin the
three properties that make the trace trustworthy:

  * it reaches the whole tree, because the bug is about which agents never ran;
  * every callback returns None, because a `before_agent_callback` returning Content
    SKIPS the agent and a `before_tool_callback` returning a dict REPLACES the tool
    result -- a tracer that got that wrong would silently become the thing it watches;
  * a turn where the root delegated to nobody says so in words that can be grepped.
"""

from __future__ import annotations

import logging

import pytest

from challenge_accepted import flow_debug


class _Ctx:
    def __init__(self, agent_name, invocation_id="inv_1", state=None, branch=""):
        self.agent_name = agent_name
        self.invocation_id = invocation_id
        self.state = state if state is not None else {}
        self.branch = branch


class _Tool:
    def __init__(self, name):
        self.name = name


@pytest.fixture(autouse=True)
def _clean():
    flow_debug._TURNS.clear()
    yield
    flow_debug._TURNS.clear()


def test_every_callback_returns_none():
    """The whole safety story. Content from before_agent_callback skips the agent."""
    ctx = _Ctx("warden")
    assert flow_debug._entered(ctx) is None
    assert flow_debug._tool_called(_Tool("write_journal"), {}, ctx) is None
    assert flow_debug._left(ctx) is None


def test_it_reaches_the_real_agent_tree():
    """Not a mock tree. If `install` silently touched nothing, the next
    unreproducible failure would be exactly as unreadable as this one was."""
    from challenge_accepted.agent import root_agent

    seen = set()
    count = flow_debug.install(root_agent, seen)
    assert count >= 6, count


def test_a_lonely_root_turn_is_called_out(caplog):
    """The open bug, in the shape the log has to make obvious."""
    ctx = _Ctx("warden", "inv_lonely")
    with caplog.at_level(logging.WARNING):
        flow_debug._entered(ctx)
        flow_debug._tool_called(_Tool("save_charter"), {}, ctx)
        flow_debug._left(ctx)

    text = caplog.text
    assert "NO HANDOFF" in text
    assert "save_charter" in text
    assert "transfers=NONE" in text


def test_a_turn_that_delegated_is_not_called_out(caplog):
    cid, root = "inv_ok", _Ctx("warden", "inv_ok")
    sub = _Ctx("cartographer", cid)
    with caplog.at_level(logging.WARNING):
        flow_debug._entered(root)
        flow_debug._tool_called(_Tool(flow_debug.TRANSFER),
                                {"agent_name": "cartographer"}, root)
        flow_debug._entered(sub)
        flow_debug._left(sub)
        flow_debug._left(root)

    assert "NO HANDOFF" not in caplog.text
    assert "handoff -> cartographer" in caplog.text
    assert "warden -> cartographer" in caplog.text


def test_the_summary_fires_on_the_root_not_on_a_sub_agent(caplog):
    """Keyed on being first into the turn, not on the name 'warden' -- hardcoding the
    root's name would go quietly silent the day it is renamed."""
    root, sub = _Ctx("warden", "inv_r"), _Ctx("interviewer", "inv_r")
    flow_debug._entered(root)
    flow_debug._entered(sub)
    with caplog.at_level(logging.WARNING):
        flow_debug._left(sub)
    assert "turn done" not in caplog.text

    with caplog.at_level(logging.WARNING):
        flow_debug._left(root)
    assert "turn done" in caplog.text


def test_the_turn_is_dropped_when_the_root_exits():
    ctx = _Ctx("warden", "inv_drop")
    flow_debug._entered(ctx)
    assert "inv_drop" in flow_debug._TURNS
    flow_debug._left(ctx)
    assert "inv_drop" not in flow_debug._TURNS


def test_turns_that_never_finish_cannot_grow_without_bound():
    """A turn is dropped when its root exits -- and the failure being chased is a turn
    whose root never does. So the leak this bounds is the exact case it observes."""
    for i in range(flow_debug._MAX_TURNS + 20):
        flow_debug._entered(_Ctx("warden", f"inv_{i}"))
    assert len(flow_debug._TURNS) <= flow_debug._MAX_TURNS + 1


def test_toolwright_entries_stay_quiet_but_still_count(caplog):
    """FORGE traces its workers in more detail than this could add; two traces of the
    same eight entries would bury the one line that matters."""
    root = _Ctx("warden", "inv_q")
    with caplog.at_level(logging.WARNING):
        flow_debug._entered(root)
        flow_debug._entered(_Ctx("toolwright_0", "inv_q"))
    assert "enter toolwright_0" not in caplog.text
    assert flow_debug._TURNS["inv_q"]["agents"] == ["warden", "toolwright_0"]


def test_a_transfer_is_recorded_as_a_handoff_not_as_a_tool():
    ctx = _Ctx("warden", "inv_t")
    flow_debug._entered(ctx)
    flow_debug._tool_called(_Tool(flow_debug.TRANSFER), {"agent_name": "forge"}, ctx)
    turn = flow_debug._TURNS["inv_t"]
    assert turn["transfers"] == ["forge"]
    assert turn["tools"] == [], "a handoff counted as an ordinary tool call hides it"


def test_running_inside_a_single_turn_sub_branch_is_called_out(caplog):
    """The other failure the trace caught, on the first run it was switched on for.

    A `mode="single_turn"` sub-agent runs in an isolated sub-branch named
    `<name>@call_<n>`. Anything still carrying that in its branch is a frame deeper
    than it should be, and dies when the tool call closes.
    """
    root = _Ctx("warden", "inv_deep")
    deep = _Ctx("forge", "inv_deep", branch="cartographer@call_636196")
    with caplog.at_level(logging.WARNING):
        flow_debug._entered(root)
        flow_debug._entered(deep)

    assert "DEEP: forge" in caplog.text
    assert "cartographer@call_636196" in caplog.text
    assert flow_debug._TURNS["inv_deep"]["deep"] == ["forge"]


def test_a_normal_branch_is_not_called_out(caplog):
    """Sub-branches are normal; `@call_` ones on a resumed parent are not. Warning on
    every branch would make the signal worthless within one run."""
    with caplog.at_level(logging.WARNING):
        flow_debug._entered(_Ctx("warden", "inv_flat"))
        flow_debug._entered(_Ctx("forge", "inv_flat", branch="forge_workers"))
    assert "DEEP" not in caplog.text


def test_the_summary_reports_depth(caplog):
    root = _Ctx("warden", "inv_sum")
    flow_debug._entered(root)
    flow_debug._entered(_Ctx("forge", "inv_sum", branch="cartographer@call_1"))
    with caplog.at_level(logging.WARNING):
        flow_debug._left(root)
    assert "deep=['forge']" in caplog.text


def test_chaining_keeps_the_callback_that_was_already_there():
    """FORGE's workers already carry before/after agent callbacks that do real work --
    resetting the per-build call counter. Replacing them would restore a fixed bug."""
    calls = []
    chained = flow_debug._chain(lambda callback_context: calls.append("theirs"),
                                lambda callback_context: calls.append("ours"))
    assert isinstance(chained, list) and len(chained) == 2
    for cb in chained:
        cb(callback_context=_Ctx("x"))
    assert calls == ["ours", "theirs"]
