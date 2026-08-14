"""Memory Bank: wired at both ends, and unable to take the app down at either.

Three things are pinned here.

1. **Sessions and memory are separate switches.** They used to share one predicate, so
   setting `AGENT_ENGINE_ID` to turn on Memory Bank would also have moved every
   conversation off the Firestore session service. Nothing would have failed; sessions
   would simply have been served by code with no test coverage in this repo.

2. **The write is best effort.** `save_charter` and `complete_node` hand the session to
   the memory service. If that call raises -- no service configured, Vertex having a
   bad minute -- the charter must still save and the node must still close.

3. **Memory is actually consulted.** A `memory_service_uri` with nothing reading it is
   a configured service that does nothing, which is precisely how the feedback button
   spent a week recording verdicts no reader ever queried.
"""

from __future__ import annotations

import importlib

from challenge_accepted import config
from challenge_accepted.agent import root_agent
from challenge_accepted.services import memory, tools
from challenge_accepted.sub_agents.interviewer import interviewer


class FakeToolContext:
    """A context with no memory API at all -- every local run and every test."""

    def __init__(self, **state):
        self.state = dict(state)


class ExplodingMemoryContext(FakeToolContext):
    """A context whose memory service is configured and broken."""

    def __init__(self, **state):
        super().__init__(**state)
        self.calls = 0

    async def add_session_to_memory(self) -> None:
        self.calls += 1
        raise RuntimeError("503 Memory Bank unavailable")


class RecordingMemoryContext(FakeToolContext):
    """A context whose memory service works."""

    def __init__(self, **state):
        super().__init__(**state)
        self.calls = 0

    async def add_session_to_memory(self) -> None:
        self.calls += 1


# --- 1. two switches, not one -------------------------------------------------

def _reload_config(monkeypatch, **env):
    for key in ("GOOGLE_CLOUD_PROJECT", "AGENT_ENGINE_ID", "CA_SESSIONS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(config)


def test_turning_on_memory_bank_does_not_move_sessions(monkeypatch):
    """The regression that would have been invisible.

    Before this split, `AGENT_ENGINE_ID` flipped sessions to Agent Engine as a side
    effect of switching on memory. Both services answer, so nothing errors -- the
    Firestore session service simply stops being the thing under test.
    """
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p", AGENT_ENGINE_ID="123")
    try:
        assert cfg.use_memory_bank() is True
        assert cfg.use_vertex_sessions() is False
    finally:
        _reload_config(monkeypatch)


def test_sessions_move_only_when_asked(monkeypatch):
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p",
                         AGENT_ENGINE_ID="123", CA_SESSIONS="agentengine")
    try:
        assert cfg.use_vertex_sessions() is True
    finally:
        _reload_config(monkeypatch)


def test_an_engine_id_without_a_project_switches_nothing(monkeypatch):
    cfg = _reload_config(monkeypatch, AGENT_ENGINE_ID="123", CA_SESSIONS="agentengine")
    try:
        assert cfg.use_memory_bank() is False
        assert cfg.use_vertex_sessions() is False
    finally:
        _reload_config(monkeypatch)


# --- 2. the write cannot take a turn down ------------------------------------

async def test_no_memory_service_is_not_an_error():
    assert await memory.remember_session(FakeToolContext()) is False


async def test_a_broken_memory_service_is_not_an_error():
    ctx = ExplodingMemoryContext()
    assert await memory.remember_session(ctx) is False
    assert ctx.calls == 1, "it should have tried"


async def test_a_working_memory_service_reports_true():
    ctx = RecordingMemoryContext()
    assert await memory.remember_session(ctx) is True
    assert ctx.calls == 1


async def test_the_charter_still_saves_when_memory_is_down():
    """The point of swallowing the exception. Losing recall is survivable; losing the
    charter the user just spent nine questions building is not."""
    ctx = ExplodingMemoryContext(user_id="u_mem", group_id="grp_u_mem")
    result = await tools.save_charter(
        title="Run a 10k",
        outcome="finish a timed 10k",
        definition_of_done="a race result with my name on it",
        deadline="2026-11-01",
        constraints=["bad knee"],
        prior_attempts=["couch to 5k, quit in week 3"],
        stakeholders=[],
        tool_context=ctx,
    )
    assert result["status"] == "ok"
    assert result["challenge_id"]
    assert ctx.calls == 1


async def test_the_charter_is_offered_to_memory():
    ctx = RecordingMemoryContext(user_id="u_mem2", group_id="grp_u_mem2")
    await tools.save_charter(
        title="Learn bread",
        outcome="a sourdough loaf with open crumb",
        definition_of_done="two good loaves in a row",
        deadline="",
        constraints=[],
        prior_attempts=[],
        stakeholders=[],
        tool_context=ctx,
    )
    assert ctx.calls == 1, "the interview is the densest source of durable facts"


async def test_closing_a_node_is_offered_to_memory():
    ctx = RecordingMemoryContext(user_id="u_mem3", group_id="grp_u_mem3")
    await tools.save_charter(
        title="Learn bread", outcome="open crumb", definition_of_done="two loaves",
        deadline="", constraints=[], prior_attempts=[], stakeholders=[],
        tool_context=ctx,
    )
    before = ctx.calls
    result = await tools.complete_node("n1", "photo of the crumb", ctx)
    assert result["status"] == "ok"
    assert ctx.calls == before + 1


async def test_closing_a_node_with_no_challenge_does_not_touch_memory():
    """Nothing durable happened, so nothing should be sent for consolidation."""
    ctx = RecordingMemoryContext(user_id="u_mem4")
    result = await tools.complete_node("n1", "evidence", ctx)
    assert result["status"] == "no_challenge"
    assert ctx.calls == 0


# --- 3. something actually reads it ------------------------------------------

def _tool_names(agent) -> list[str]:
    return [getattr(t, "name", getattr(t, "__name__", "")) for t in agent.tools]


def test_warden_reads_memory():
    assert "preload_memory" in _tool_names(root_agent)


def test_the_interviewer_reads_memory():
    """Where it pays: a question already answered in a past challenge is a question
    this interview does not need to ask."""
    assert "preload_memory" in _tool_names(interviewer)


def test_preload_memory_is_not_model_callable():
    """It must not consume a slot against the tool-count ceiling.

    `PreloadMemoryTool` hooks `process_llm_request` and declares no function, so the
    model never sees it. If a future ADK version starts declaring it, the FORGE
    tool-count budget changes and we want to hear about it here rather than from a
    truncated tool list in a live run.
    """
    from google.adk.tools.preload_memory_tool import preload_memory_tool

    assert preload_memory_tool._get_declaration() is None
