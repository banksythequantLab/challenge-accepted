"""`include_contents="none"` does not survive a second loop iteration.

It filters *session history*. It does not clear what the flow accumulates inside a
single invocation -- and the LoopAgent re-runs the same worker instances, so on
iteration two a worker's very first model call arrives carrying iteration one's build.

Measured live: iteration one's first call had `contents=1`; iteration two's had
`contents=4`, `spec_in_prompt=True`, and the worker ended 1.5 seconds later without
calling `save_tool`. That is precisely the failure `include_contents="none"` was added
to prevent, described in `_worker`'s own comment: the worker sees the tool it already
built and writes confident prose about it instead of building the new one.

Six specs in, four tools out, and the two dropped ones looked exactly like specs that
were never needed.
"""

from __future__ import annotations

import importlib

from google.genai import types

from challenge_accepted import config


class _Ctx:
    """The CallbackContext surface both callbacks touch."""

    def __init__(self, agent_name="toolwright_0", invocation_id="inv_1", slot=None):
        self.agent_name = agent_name
        self.invocation_id = invocation_id
        self.branch = f"forge_workers.{agent_name}"
        self.state = {"forge_slot_0": slot}


class _Req:
    def __init__(self, contents):
        self.contents = contents
        self.config = None


def _content(text):
    return types.Content(role="user", parts=[types.Part(text=text)])


def _forge(monkeypatch):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    importlib.reload(config)
    mod = importlib.reload(importlib.import_module("challenge_accepted.sub_agents.forge"))
    mod._CALLS_THIS_BUILD.clear()
    return mod


def test_the_first_call_of_a_build_drops_a_previous_iteration(monkeypatch):
    forge = _forge(monkeypatch)
    ctx = _Ctx(slot={"node_id": "n2"})

    forge._saw_its_slot(0)(ctx)              # iteration two begins
    req = _Req([_content("the tool I built last time"), _content("and its output")])
    forge._prepare_worker_request(ctx, req)

    assert req.contents == [], (
        "a fresh slot must not see the previous build, or the worker narrates the old "
        "tool instead of making the new one")


def test_later_calls_in_the_same_build_keep_their_history(monkeypatch):
    """The code-execute-then-fix loop needs to see what it just ran. Clearing every
    call would break building a tool at all."""
    forge = _forge(monkeypatch)
    ctx = _Ctx(slot={"node_id": "n2"})
    forge._saw_its_slot(0)(ctx)

    forge._prepare_worker_request(ctx, _Req([_content("stale")]))          # call 1: cleared
    kept = _Req([_content("code I just ran"), _content("its output")])
    forge._prepare_worker_request(ctx, kept)                               # call 2: kept
    assert len(kept.contents) == 2


def test_each_iteration_gets_a_clean_slate(monkeypatch):
    """Three iterations of the same worker, exactly as the LoopAgent drives it."""
    forge = _forge(monkeypatch)
    ctx = _Ctx(slot={"node_id": "n"})
    for _ in range(3):
        forge._saw_its_slot(0)(ctx)
        first = _Req([_content("leftovers from the last slot")])
        forge._prepare_worker_request(ctx, first)
        assert first.contents == []
        second = _Req([_content("this build's own code")])
        forge._prepare_worker_request(ctx, second)
        assert len(second.contents) == 1
        forge._finished(0)(ctx)


def test_workers_do_not_clear_each_other(monkeypatch):
    """Four workers run concurrently in one invocation; the key must separate them."""
    forge = _forge(monkeypatch)
    a, b = _Ctx("toolwright_0"), _Ctx("toolwright_1")
    forge._saw_its_slot(0)(a)
    forge._prepare_worker_request(a, _Req([_content("x")]))   # a's first call, cleared

    # b has not started, so nothing of b's should be treated as a fresh build.
    keep = _Req([_content("b mid-build")])
    forge._prepare_worker_request(b, keep)
    assert len(keep.contents) == 1, "an unstarted worker must not be cleared"

    forge._saw_its_slot(0)(b)
    fresh = _Req([_content("b stale")])
    forge._prepare_worker_request(b, fresh)
    assert fresh.contents == []


def test_the_counter_does_not_leak(monkeypatch):
    """One int per worker per invocation, and it goes when the worker does."""
    forge = _forge(monkeypatch)
    ctx = _Ctx()
    forge._saw_its_slot(0)(ctx)
    assert forge._CALLS_THIS_BUILD
    forge._finished(0)(ctx)
    assert not forge._CALLS_THIS_BUILD
