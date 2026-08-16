"""The Vertex `id` guard, tested where it actually broke: the ROOT agent.

The original guard was on the Toolwrights, which is where the code executes -- and it
was still the root agent that crashed, because the root runs unbranched and therefore
sees every event in the invocation, including the Toolwrights'. These tests assert the
scope, not just the mechanism, because the mechanism was never wrong.
"""

from __future__ import annotations

import types as pytypes

import pytest
from google.genai import types

from challenge_accepted import vertex_compat
from challenge_accepted.agent import root_agent


def _request_with_code_ids():
    """An llm_request shaped like the one that raised in production."""
    return pytypes.SimpleNamespace(contents=[
        types.Content(role="user", parts=[types.Part(text="build it")]),
        types.Content(role="model", parts=[
            types.Part(executable_code=types.ExecutableCode(
                code="print(1)", language="PYTHON", id="ec_1")),
        ]),
        types.Content(role="user", parts=[
            types.Part(code_execution_result=types.CodeExecutionResult(
                outcome="OUTCOME_OK", output="1", id="cer_1")),
        ]),
    ])


def _ids(req):
    out = []
    for content in req.contents:
        for part in content.parts:
            for attr in ("executable_code", "code_execution_result"):
                blob = getattr(part, attr, None)
                if blob is not None:
                    out.append(getattr(blob, "id", None))
    return out


def _callbacks(agent):
    cb = getattr(agent, "before_model_callback", None)
    if cb is None:
        return []
    return list(cb) if isinstance(cb, list) else [cb]


def _walk(agent, seen=None):
    seen = seen if seen is not None else set()
    if agent is None or id(agent) in seen:
        return []
    seen.add(id(agent))
    found = [agent]
    for sub in getattr(agent, "sub_agents", None) or []:
        found += _walk(sub, seen)
    for tool in getattr(agent, "tools", None) or []:
        inner = getattr(tool, "agent", None)
        if inner is not None:
            found += _walk(inner, seen)
    return found


def test_strip_removes_both_id_kinds_on_vertex(monkeypatch):
    monkeypatch.setattr(vertex_compat.config, "use_vertex_models", lambda: True)
    req = _request_with_code_ids()
    assert _ids(req) == ["ec_1", "cer_1"]
    vertex_compat.strip_code_ids(None, req)
    assert _ids(req) == [None, None]


def test_strip_leaves_the_developer_api_alone(monkeypatch):
    """The id is legal there, and ADK uses it to pair a result with its code."""
    monkeypatch.setattr(vertex_compat.config, "use_vertex_models", lambda: False)
    req = _request_with_code_ids()
    vertex_compat.strip_code_ids(None, req)
    assert _ids(req) == ["ec_1", "cer_1"]


def test_the_root_agent_is_guarded():
    """The regression itself.

    Warden crashed with `id parameter is only supported in Gemini Developer API mode`
    at the end of every FORGE turn, because the guard was only on the Toolwrights.
    """
    assert vertex_compat.strip_code_ids in _callbacks(root_agent), (
        "the root agent has no Vertex id guard -- it runs unbranched and sees the "
        "Toolwrights' executableCode events, which is exactly what raised")


def test_every_agent_that_calls_a_model_is_guarded():
    """Only the model-calling agents need it, and all of them must have it.

    `forge`, `forge_loop`, `dispatcher` and `forge_workers` are Sequential/Loop/
    Parallel/BaseAgent orchestration: they route events and never build a
    GenerateContent request, so there is nothing for a `before_model_callback` to
    guard. Asserting they carry one would be asserting a fiction -- but every agent
    that DOES reach `generate_content` has to, since any of them can be handed history
    containing a code part.
    """
    from google.adk.agents import LlmAgent

    agents = _walk(root_agent)
    assert len(agents) >= 6, f"only found {len(agents)} agents to check"
    callers = [a for a in agents if isinstance(a, LlmAgent)]
    assert len(callers) >= 6, f"only {len(callers)} model-calling agents found"
    missing = [a.name for a in callers
               if vertex_compat.strip_code_ids not in _callbacks(a)]
    assert not missing, f"model-calling agents with no Vertex id guard: {missing}"


def test_install_keeps_callbacks_the_agent_already_had():
    """The Toolwrights carry their own callback and must not lose it."""
    calls = []

    def existing(ctx, req):
        calls.append("existing")

    agent = pytypes.SimpleNamespace(
        before_model_callback=existing, sub_agents=[], tools=[], name="x")
    assert vertex_compat.install(agent) == 1
    cbs = _callbacks(agent)
    assert vertex_compat.strip_code_ids in cbs and existing in cbs
    # Ours runs first, so a pre-existing callback never sees a request that would
    # have crashed the call.
    assert cbs[0] is vertex_compat.strip_code_ids


def test_install_reports_what_it_touched():
    """A silent no-op here would restore the bug and look like success."""
    tree = pytypes.SimpleNamespace(
        before_model_callback=None, name="root", tools=[],
        sub_agents=[pytypes.SimpleNamespace(before_model_callback=None, name="kid",
                                            sub_agents=[], tools=[])])
    assert vertex_compat.install(tree) == 2


@pytest.mark.parametrize("bad", [None, pytypes.SimpleNamespace()])
def test_install_survives_things_that_are_not_agents(bad):
    assert vertex_compat.install(bad) in (0, 1)
