"""The `id` on code parts that Vertex will not take back.

A Toolwright's first model call returns an `executableCode` part carrying an `id`. ADK
keeps it in the agent's history, and the worker's *second* call sends it back:

    ValueError: id parameter is only supported in Gemini Developer API mode, not in
    Gemini Enterprise Agent Platform mode.
      File "google/genai/models.py", line 1188, in _ExecutableCode_to_vertex

Workers run inside an `asyncio.TaskGroup`, so one failure cancels the siblings. That is
why the deployed service built exactly one tool out of seven, every single time,
with no error visible in the product and a dashboard that looked finished.

These assert against `google.genai`'s real converters, not a fake of them: if a future
version drops the guard, or adds the same guard somewhere new, that is exactly when we
want to hear about it.
"""

from __future__ import annotations

import importlib

import pytest
from google.genai import types

from challenge_accepted import config


class _Req:
    def __init__(self, contents):
        self.contents = contents


def _history_with_ids():
    """What a worker's second call actually carries after one code execution."""
    return [
        types.Content(role="model", parts=[
            types.Part(executable_code=types.ExecutableCode(
                code="print(1)", language="PYTHON", id="ec_abc123")),
        ]),
        types.Content(role="user", parts=[
            types.Part(code_execution_result=types.CodeExecutionResult(
                outcome="OUTCOME_OK", output="1", id="cer_def456")),
        ]),
        types.Content(role="user", parts=[types.Part(text="plain text is untouched")]),
    ]


def _reload(monkeypatch, vertex: bool):
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    if vertex:
        monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    importlib.reload(config)
    return importlib.reload(importlib.import_module("challenge_accepted.sub_agents.forge"))


def test_ids_are_stripped_in_vertex_mode(monkeypatch):
    forge = _reload(monkeypatch, vertex=True)
    try:
        req = _Req(_history_with_ids())
        forge._prepare_worker_request(None, req)
        assert req.contents[0].parts[0].executable_code.id is None
        assert req.contents[1].parts[0].code_execution_result.id is None
        assert req.contents[0].parts[0].executable_code.code == "print(1)", "code kept"
        assert req.contents[1].parts[0].code_execution_result.output == "1", "output kept"
        assert req.contents[2].parts[0].text == "plain text is untouched"
    finally:
        _reload(monkeypatch, vertex=False)


def test_ids_are_left_alone_on_the_developer_api(monkeypatch):
    """They are legal there, and removing them would be an unforced change to a path
    that has always worked."""
    forge = _reload(monkeypatch, vertex=False)
    req = _Req(_history_with_ids())
    forge._prepare_worker_request(None, req)
    assert req.contents[0].parts[0].executable_code.id == "ec_abc123"
    assert req.contents[1].parts[0].code_execution_result.id == "cer_def456"


def test_google_genai_still_rejects_these_ids():
    """The reason `_prepare_worker_request` exists. Drive the real converters.

    If a future google-genai stops raising, this fails and the stripping becomes
    optional. If it starts raising on a *third* field, the round-trip test below is
    what catches it -- because that is the shape of this bug: a legal-looking value
    that only explodes on the way back.
    """
    from google.genai import models

    with pytest.raises(ValueError, match="only supported in Gemini Developer API"):
        models._ExecutableCode_to_vertex(
            types.ExecutableCode(code="print(1)", language="PYTHON", id="ec_abc123"))

    with pytest.raises(ValueError, match="only supported in Gemini Developer API"):
        models._CodeExecutionResult_to_vertex(
            types.CodeExecutionResult(outcome="OUTCOME_OK", output="1", id="cer_x"))


def test_a_stripped_history_survives_the_real_vertex_converter(monkeypatch):
    """End to end against google-genai itself: after stripping, every part in a
    worker's history converts cleanly. This is the assertion that would have caught
    the outage before it shipped."""
    from google.genai import models

    forge = _reload(monkeypatch, vertex=True)
    try:
        req = _Req(_history_with_ids())
        forge._prepare_worker_request(None, req)
        for content in req.contents:
            for part in content.parts:
                models._Part_to_vertex(part)  # raises if anything illegal survived
    finally:
        _reload(monkeypatch, vertex=False)
