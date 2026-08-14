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
    for key in ("GOOGLE_CLOUD_PROJECT", "AGENT_ENGINE_ID", "CA_SESSIONS",
                "GOOGLE_CLOUD_LOCATION", "AGENT_ENGINE_LOCATION",
                "CA_TRACE_TO_CLOUD"):
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


# --- 1b. the engine's region does not come from the model's region ------------

def test_the_engine_region_survives_a_global_model_endpoint(monkeypatch):
    """The trap this would have walked into on the very first deploy.

    Production sets `GOOGLE_CLOUD_LOCATION=global`, because Gemini 3.x is served from
    the global endpoint. ADK, handed a bare engine id, reads project and location from
    exactly those variables -- so Memory Bank would have been built against a `global`
    Agent Engine, which does not exist. And it would have failed silently, because both
    ends swallow their errors on purpose: the app would run perfectly and remember
    nothing. Emitting the full resource path is what stops that.
    """
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p",
                         AGENT_ENGINE_ID="123", GOOGLE_CLOUD_LOCATION="global")
    try:
        assert cfg.agent_engine_resource() == (
            "projects/p/locations/us-central1/reasoningEngines/123")
        assert "global" not in cfg.agent_engine_resource()
    finally:
        _reload_config(monkeypatch)


def test_a_full_resource_name_is_passed_through(monkeypatch):
    full = "projects/other/locations/europe-west4/reasoningEngines/9"
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p", AGENT_ENGINE_ID=full)
    try:
        assert cfg.agent_engine_resource() == full
    finally:
        _reload_config(monkeypatch)


def test_the_engine_region_is_overridable(monkeypatch):
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p", AGENT_ENGINE_ID="123",
                         AGENT_ENGINE_LOCATION="europe-west4")
    try:
        assert cfg.agent_engine_resource().endswith(
            "locations/europe-west4/reasoningEngines/123")
    finally:
        _reload_config(monkeypatch)


def test_memory_bank_does_not_switch_on_cloud_trace(monkeypatch):
    """Revision 00014 crash-looped on exactly this.

    `trace_to_cloud` shared the predicate too, so the first deploy that set
    AGENT_ENGINE_ID made ADK import an OpenTelemetry exporter that was not installed,
    and the container died before binding the port.
    """
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p", AGENT_ENGINE_ID="123")
    try:
        assert cfg.use_memory_bank() is True
        assert cfg.use_cloud_trace() is False
    finally:
        _reload_config(monkeypatch)


def test_cloud_trace_switches_on_when_asked(monkeypatch):
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p", CA_TRACE_TO_CLOUD="1")
    try:
        assert cfg.use_cloud_trace() is True
    finally:
        _reload_config(monkeypatch)


def test_no_engine_means_no_resource(monkeypatch):
    cfg = _reload_config(monkeypatch, GOOGLE_CLOUD_PROJECT="p")
    try:
        assert cfg.agent_engine_resource() is None
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
    assert memory.preload_memory._get_declaration() is None


# --- 4. the negative cache, and the private API it leans on -------------------

class _Resp:
    def __init__(self, memories):
        self.memories = memories


class _Req:
    def __init__(self):
        self.injected = []

    def _append_dynamic_instructions(self, items):
        self.injected.extend(items)


class _PreloadCtx:
    """Enough ToolContext surface for `process_llm_request`."""

    def __init__(self, text, memories, app="challenge_accepted", user="u1"):
        from google.genai import types
        self.user_content = types.Content(role="user", parts=[types.Part(text=text)])
        self.user_id = user
        self.session = type("S", (), {"app_name": app})()
        self._memories = memories
        self.searches = 0

    async def search_memory(self, query):
        self.searches += 1
        return _Resp(self._memories)


def _clear_cache():
    memory._EMPTY_UNTIL.clear()
    memory._HAS_WRITTEN.clear()


async def test_an_empty_search_after_a_write_is_not_cached():
    """The regression that shipped, deployed, and broke live recall.

    Memory Bank generates asynchronously -- about 30 seconds. So the turn that writes
    is followed almost immediately by more preload searches that still find nothing.
    The first version of this cache believed them and re-armed a 300-second marker, and
    every probe after that skipped the search entirely. The memories were provably in
    Memory Bank the whole time; the app simply stopped looking.

    Clearing the marker on write is not enough. The write must make the user
    permanently uncacheable in this process.
    """
    _clear_cache()
    app, user = "challenge_accepted", "u_race"

    memory.mark_empty(app, user)                 # T+0   turn one finds nothing
    assert memory.looks_empty(app, user) is True

    memory.forget_empty(app, user)               # T+90  save_charter writes
    assert memory.looks_empty(app, user) is False

    memory.mark_empty(app, user)                 # T+95  still generating, still empty
    assert memory.looks_empty(app, user) is False, (
        "an empty search after a write is Memory Bank still generating, not proof of "
        "no past -- caching it costs the user recall for a full TTL")
    _clear_cache()


async def test_the_write_path_end_to_end_leaves_the_user_uncacheable():
    """Same guarantee, but reached through `remember_session` rather than by hand --
    because the bug lived in the gap between what the helpers do and what the real
    call site actually reaches."""
    _clear_cache()
    ctx = RecordingMemoryContext(user_id="u_e2e")
    ctx.user_id = "u_e2e"
    ctx.session = type("S", (), {"app_name": "challenge_accepted"})()

    memory.mark_empty("challenge_accepted", "u_e2e")
    assert await memory.remember_session(ctx) is True

    tool, req = memory.PreloadMemory(), _Req()
    probe = _PreloadCtx("what do you know about me?", memories=[], user="u_e2e")
    await tool.process_llm_request(tool_context=probe, llm_request=req)
    assert probe.searches == 1, "a user we have written for is always searched"

    later = _PreloadCtx("and my goal?", memories=[], user="u_e2e")
    await tool.process_llm_request(tool_context=later, llm_request=req)
    assert later.searches == 1, "still searched -- the empty result must not stick"
    _clear_cache()


async def test_an_empty_search_is_remembered_and_not_repeated():
    """The whole point. Measured live: an empty search costs ~1.8s, and Warden and the
    Interviewer each pay it on every LLM request of a nine-question interview."""
    _clear_cache()
    tool, req = memory.PreloadMemory(), _Req()
    ctx = _PreloadCtx("I want to run a 10k", memories=[])
    await tool.process_llm_request(tool_context=ctx, llm_request=req)
    assert ctx.searches == 1
    assert memory.looks_empty("challenge_accepted", "u1") is True

    again = _PreloadCtx("and I only have Tuesdays", memories=[])
    await tool.process_llm_request(tool_context=again, llm_request=req)
    assert again.searches == 0, "the second turn should not re-ask"
    _clear_cache()


async def test_a_hit_is_injected_and_never_cached():
    """Positive results are semantic matches against what the user just typed. Serving
    turn one's matches on turn four would trade recall quality for latency."""
    from google.genai import types
    _clear_cache()
    hit = type("M", (), {
        "timestamp": None, "author": "user",
        "content": types.Content(parts=[types.Part(text="I train Tuesdays only")]),
    })()
    tool, req = memory.PreloadMemory(), _Req()
    ctx = _PreloadCtx("what do you know about me?", memories=[hit])
    await tool.process_llm_request(tool_context=ctx, llm_request=req)

    assert ctx.searches == 1
    assert len(req.injected) == 1
    assert "I train Tuesdays only" in req.injected[0]
    assert "<PAST_CONVERSATIONS>" in req.injected[0]
    assert memory.looks_empty("challenge_accepted", "u1") is False, "never cache a hit"

    second = _PreloadCtx("and my goal?", memories=[hit])
    await tool.process_llm_request(tool_context=second, llm_request=req)
    assert second.searches == 1, "a user with memories is searched every turn"
    _clear_cache()


async def test_writing_a_memory_clears_the_empty_marker():
    """Otherwise the user's first saved charter is invisible until the TTL expires."""
    _clear_cache()
    memory.mark_empty("challenge_accepted", "u_new")
    assert memory.looks_empty("challenge_accepted", "u_new") is True

    ctx = RecordingMemoryContext(user_id="u_new")
    ctx.user_id = "u_new"
    ctx.session = type("S", (), {"app_name": "challenge_accepted"})()
    assert await memory.remember_session(ctx) is True
    assert memory.looks_empty("challenge_accepted", "u_new") is False
    _clear_cache()


async def test_a_failed_write_leaves_the_marker_alone():
    """Nothing was stored, so nothing changed about what they have."""
    _clear_cache()
    memory.mark_empty("challenge_accepted", "u_x")
    ctx = ExplodingMemoryContext()
    ctx.user_id = "u_x"
    ctx.session = type("S", (), {"app_name": "challenge_accepted"})()
    assert await memory.remember_session(ctx) is False
    assert memory.looks_empty("challenge_accepted", "u_x") is True
    _clear_cache()


async def test_a_broken_search_is_not_cached_as_empty():
    """An outage is not evidence that the user has no past. Caching it would suppress
    recall for the whole TTL after a single blip."""
    _clear_cache()

    class Boom(_PreloadCtx):
        async def search_memory(self, query):
            self.searches += 1
            raise RuntimeError("503")

    tool, req = memory.PreloadMemory(), _Req()
    ctx = Boom("hello", memories=[])
    await tool.process_llm_request(tool_context=ctx, llm_request=req)
    assert req.injected == []
    assert memory.looks_empty("challenge_accepted", "u1") is False
    _clear_cache()


def test_the_private_adk_method_we_depend_on_still_exists():
    """`PreloadMemory` copies ADK 2.6.3's inject step, which calls a private method.

    If an upgrade renames it, every memory injection would vanish silently -- the app
    would run perfectly and recall nothing, which is exactly how the feedback button
    spent a month writing rows no reader queried. Fail here instead.
    """
    from google.adk.models import LlmRequest

    assert hasattr(LlmRequest, "_append_dynamic_instructions")
