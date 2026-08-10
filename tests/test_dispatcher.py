"""Dispatcher tests.

These run with no API key: Dispatcher is a deterministic BaseAgent, so it can be driven
through a real ADK Runner without ever calling a model. That is the point of making it
a custom agent rather than an LlmAgent -- the fan-out logic is testable.
"""

from __future__ import annotations

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from challenge_accepted.sub_agents.forge import SLOT_PREFIX, Dispatcher

APP = "ca_test"
USER = "u1"


def _spec(node_id: str, needed: bool = True) -> dict:
    return {
        "node_id": node_id,
        "needed": needed,
        "tool_type": "calculator",
        "name": f"{node_id}-calc",
        "purpose": "test",
        "inputs": [],
        "outputs": [],
        "smoke_test": "1 -> 1",
    }


async def _run_once(initial_state: dict) -> dict:
    """Run Dispatcher once and return the resulting session state."""
    runner = InMemoryRunner(agent=Dispatcher(name="dispatcher", description="test"),
                            app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id=USER, state=initial_state
    )
    async for _ in runner.run_async(
        user_id=USER,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="go")]),
    ):
        pass
    refreshed = await runner.session_service.get_session(
        app_name=APP, user_id=USER, session_id=session.id
    )
    return dict(refreshed.state)


@pytest.mark.asyncio
async def test_fills_all_slots_and_leaves_remainder_queued():
    specs = [_spec(f"n{i}") for i in range(6)]
    state = await _run_once({"tool_specs": {"specs": specs}})

    assigned = [state.get(f"{SLOT_PREFIX}{i}") for i in range(4)]
    assert [a["node_id"] for a in assigned] == ["n0", "n1", "n2", "n3"]
    assert [s["node_id"] for s in state["forge.queue"]] == ["n4", "n5"]


@pytest.mark.asyncio
async def test_skips_specs_that_need_no_tool():
    specs = [_spec("keep"), _spec("drop", needed=False), _spec("keep2")]
    state = await _run_once({"tool_specs": {"specs": specs}})

    node_ids = [state[f"{SLOT_PREFIX}{i}"]["node_id"]
                for i in range(4) if state.get(f"{SLOT_PREFIX}{i}")]
    assert node_ids == ["keep", "keep2"]
    assert state["forge.queue"] == []


@pytest.mark.asyncio
async def test_idle_slots_are_cleared_not_stale():
    """A worker whose slot is None must see None, not the previous batch's spec."""
    state = await _run_once({"tool_specs": {"specs": [_spec("only")]},
                             f"{SLOT_PREFIX}3": _spec("stale")})
    assert state[f"{SLOT_PREFIX}3"] is None


@pytest.mark.asyncio
async def test_accepts_json_string_output_from_quartermaster():
    """output_schema can arrive as a JSON string depending on the model path."""
    import json

    state = await _run_once({"tool_specs": json.dumps({"specs": [_spec("n0")]})})
    assert state[f"{SLOT_PREFIX}0"]["node_id"] == "n0"


@pytest.mark.asyncio
async def test_empty_queue_terminates_the_loop():
    state = await _run_once({"tool_specs": {"specs": []}})
    assert all(state.get(f"{SLOT_PREFIX}{i}") is None for i in range(4))
    assert state["forge.queue"] == []
