"""The parameter that made FORGE work locally and killed it in production.

`include_server_side_tool_invocations` is required on the Gemini Developer API to let
one agent both execute code and call a function. On Vertex it is not merely ignored --
`google-genai` raises on the parameter itself:

    ValueError: include_server_side_tool_invocations parameter is only supported in
    Gemini Developer API mode, not in Gemini Enterprise Agent Platform mode.

Local runs use a `GOOGLE_API_KEY`; the deploy sets `GOOGLE_GENAI_USE_VERTEXAI=TRUE`. So
every Toolwright on every deployed revision died while local runs built four to six
tools each time. Ten challenges in production Firestore, every agent-driven one with
`tools: []`, and nothing in the product looked wrong: deploy green, health green, graph
drawn, journal filling, FORGE rail animating around an empty result.

These tests are cheap and they are the only thing standing between that flag and the
next environment where it is illegal.
"""

from __future__ import annotations

import importlib

from challenge_accepted import config


def _reload(monkeypatch, value=None):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    if value is not None:
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", value)
    cfg = importlib.reload(config)
    forge = importlib.reload(importlib.import_module("challenge_accepted.sub_agents.forge"))
    return cfg, forge


def test_vertex_never_receives_the_illegal_parameter(monkeypatch):
    """The production case. `TRUE` is exactly what deploy.ps1 sets."""
    cfg, forge = _reload(monkeypatch, "TRUE")
    try:
        assert cfg.use_vertex_models() is True
        assert forge._worker_config().tool_config is None, (
            "Vertex raises on this parameter; it must be absent, not falsy")
    finally:
        _reload(monkeypatch)


def test_the_developer_api_still_gets_it(monkeypatch):
    """The local case, and the reason the flag exists at all: without it the Developer
    API rejects the whole request with a 400 and no Toolwright can save anything."""
    cfg, forge = _reload(monkeypatch)
    try:
        assert cfg.use_vertex_models() is False
        cfgobj = forge._worker_config()
        assert cfgobj.tool_config is not None
        assert cfgobj.tool_config.include_server_side_tool_invocations is True
    finally:
        _reload(monkeypatch)


def test_the_flag_follows_the_variable_google_genai_actually_reads(monkeypatch):
    """Our idea of the mode and the client's must never diverge -- that divergence is
    the entire bug. Cover the spellings google-genai accepts."""
    for value, expected in (("1", True), ("true", True), ("True", True),
                            ("TRUE", True), ("0", False), ("false", False), ("", False)):
        cfg, _ = _reload(monkeypatch, value)
        assert cfg.use_vertex_models() is expected, f"{value!r} read as {not expected}"
    _reload(monkeypatch)


def test_a_worker_is_still_constructible_in_both_modes(monkeypatch):
    """A config split is worthless if it throws while building the agent."""
    for value in ("TRUE", None):
        _, forge = _reload(monkeypatch, value)
        worker = forge._worker(0)
        assert worker.name == "toolwright_0"
        assert worker.code_executor is not None
        assert [t.__name__ for t in worker.tools] == ["save_tool"]
    _reload(monkeypatch)
