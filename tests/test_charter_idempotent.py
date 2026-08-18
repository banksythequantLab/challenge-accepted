"""Calling save_charter twice must not orphan a challenge.

Measured on production. One FORGE run produced two challenges four minutes apart with
the same title, and the second was empty. The turn had failed mid-flight, the Warden
recovered by re-running ACCEPT, and `save_charter` -- which only knew how to create --
made a second challenge and pointed session state at it. Twelve nodes, six tools and
every journal entry stayed on the first one, invisible.

`check_forge_live.py` reported "0 tools built. This is the money shot." It was right
that something was broken and wrong about what: FORGE had worked perfectly.

The tool's docstring says "call this exactly once". An instruction is not a constraint.
Anything a model can do twice it eventually will -- on a retry, after a crash, or
because the user changed their mind halfway through -- and losing a challenge's entire
contents is a bad outcome for a duplicate function call.
"""

from __future__ import annotations

import asyncio

import pytest

from challenge_accepted.services import tools
from challenge_accepted.services.store import store


class _Ctx:
    """The slice of ToolContext these tools touch."""

    def __init__(self, state=None):
        self.state = dict(state or {})


@pytest.fixture()
def ctx() -> _Ctx:
    return _Ctx({"user_id": "uid_derek", "group_id": "grp_charter_test"})


def _save(ctx, outcome="ship the app", title="Ship it"):
    # `save_charter` is async; driven with asyncio.run rather than an async test so
    # this file needs no plugin configuration to stay runnable.
    return asyncio.run(tools.save_charter(
        title=title, outcome=outcome, definition_of_done="deployed",
        deadline="the 30th", constraints=["evenings only"],
        prior_attempts=[], stakeholders=[], tool_context=ctx))


def test_the_first_call_creates(ctx):
    got = _save(ctx)
    assert got["status"] == "ok"
    assert ctx.state["challenge_id"] == got["challenge_id"]


def test_the_second_call_updates_the_same_challenge(ctx):
    first = _save(ctx)["challenge_id"]
    second = _save(ctx, outcome="ship the app by Friday")

    assert second["status"] == "updated"
    assert second["challenge_id"] == first, "a second charter minted a rival challenge"
    assert ctx.state["challenge_id"] == first
    charter = store.get("challenges", first)["charter"]
    assert charter["outcome"] == "ship the app by Friday", "the update did not land"


def test_the_second_call_does_not_orphan_what_was_already_built(ctx):
    """The actual damage. Nodes, tools and journal all hang off the challenge id."""
    cid = _save(ctx)["challenge_id"]
    store.put_node(cid, {"id": "spike", "title": "Spike", "acceptance_criteria": "a",
                         "depends_on": []})
    store.put_tool(cid, "spike", {"type": "checklist", "name": "Checks", "source": "{}",
                                  "usage": "u", "smoke_test_passed": True,
                                  "degraded": False})

    _save(ctx, outcome="ship the app by Friday")

    assert ctx.state["challenge_id"] == cid
    assert len(store.list_nodes(cid)) == 1
    assert len(store.list_tools(cid)) == 1, (
        "the work is on a challenge nobody is pointing at any more")


def test_a_stale_challenge_id_still_creates(ctx):
    """Session state can outlive the store -- a wiped collection, a fresh project.

    Falling through to create is right here; refusing would leave the user unable to
    start anything at all, which is a worse failure than a duplicate.
    """
    ctx.state["challenge_id"] = "chal_deleted_long_ago"
    got = _save(ctx)
    assert got["status"] == "ok"
    assert got["challenge_id"] != "chal_deleted_long_ago"


def test_the_model_is_told_what_happened(ctx):
    """It has to be able to tell "updated" from "created" -- otherwise it will
    cheerfully announce a brand-new quest to somebody mid-way through their old one."""
    _save(ctx)
    note = _save(ctx)["note"]
    assert "already existed" in note
    assert "still attached" in note
