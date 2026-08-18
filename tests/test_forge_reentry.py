"""FORGE must work the SECOND time it is entered, not just the first.

Found live: a session ran FORGE twice (Warden delegated to it on two consecutive
turns). The first pass drained the queue to []. On the second pass the Dispatcher saw
a non-None queue, treated it as authoritative, and escalated immediately -- silently
discarding every new ToolSpec the Quartermaster had just produced.

Nothing about that is visible in the output. The run just quietly builds no tools.
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
from google.adk.agents import BaseAgent, LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import InMemoryRunner
from google.genai import types


async def _set_specs(runner: InMemoryRunner, session_id: str, specs: list[dict]) -> None:
    """Write new tool_specs into the stored session.

    Mutating the object returned by get_session does nothing -- InMemorySessionService
    hands back a copy. State changes must go through an event's state_delta, which is
    also how the Quartermaster's output_key writes it in the real pipeline.
    """
    session = await runner.session_service.get_session(
        app_name=APP, user_id=USER, session_id=session_id
    )
    await runner.session_service.append_event(
        session,
        Event(author="test", invocation_id="setup",
              actions=EventActions(state_delta={"tool_specs": {"specs": specs}})),
    )

from challenge_accepted import config
from challenge_accepted.sub_agents.forge import QUEUE_KEY, SLOT_PREFIX, Dispatcher

APP = "forge_reentry"
USER = "u1"

SEEN: list[list[str]] = []


class RecordingWorkers(BaseAgent):
    #: Mirror the real fan-out width rather than hardcoding it, or this stand-in reads
    #: slots the Dispatcher was never asked to fill.
    workers: int = config.FORGE_WORKERS

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        batch = [
            ctx.session.state[f"{SLOT_PREFIX}{i}"]["node_id"]
            for i in range(self.workers)
            if ctx.session.state.get(f"{SLOT_PREFIX}{i}")
        ]
        if batch:
            SEEN.append(batch)
        yield Event(author=self.name, invocation_id=ctx.invocation_id, branch=ctx.branch)


def _spec(node_id: str) -> dict:
    return {"node_id": node_id, "needed": True, "tool_type": "calculator",
            "name": node_id, "purpose": "p", "inputs": [], "outputs": [],
            "smoke_test": "x"}


def _loop() -> LoopAgent:
    return LoopAgent(
        name="forge_loop", description="test", max_iterations=6,
        sub_agents=[Dispatcher(name="dispatcher", description="d"),
                    RecordingWorkers(name="workers", description="w")],
    )


async def _run(runner: InMemoryRunner, session_id: str) -> None:
    async for _ in runner.run_async(
        user_id=USER, session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text="go")]),
    ):
        pass


@pytest.mark.asyncio
async def test_second_forge_entry_dispatches_the_new_specs():
    SEEN.clear()
    first = [_spec("a1"), _spec("a2")]
    runner = InMemoryRunner(agent=_loop(), app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id=USER, state={"tool_specs": {"specs": first}}
    )

    await _run(runner, session.id)
    assert SEEN == [["a1", "a2"]], f"first pass: {SEEN}"

    # Quartermaster runs again on a redrawn graph and writes a fresh spec set.
    await _set_specs(runner, session.id, [_spec("b1"), _spec("b2"), _spec("b3")])

    SEEN.clear()
    await _run(runner, session.id)

    # Assert on the specs that reached workers, not on how they were batched: the
    # batch width is a tuning knob (`config.FORGE_WORKERS`, lowered from 4 to 2 after
    # measuring the live service) and this test is about reseeding, not concurrency.
    assert [node for batch in SEEN for node in batch] == ["b1", "b2", "b3"], (
        f"second pass dispatched {SEEN} -- the new specs were dropped because the "
        f"drained queue from the first pass was treated as authoritative."
    )
    assert all(len(batch) <= config.FORGE_WORKERS for batch in SEEN), SEEN
    final = await runner.session_service.get_session(
        app_name=APP, user_id=USER, session_id=session.id
    )
    assert final.state.get(QUEUE_KEY) == []


@pytest.mark.asyncio
async def test_reentry_with_identical_specs_does_not_rebuild():
    """Re-entering with the SAME specs must not redo work already dispatched."""
    SEEN.clear()
    specs = [_spec("x1"), _spec("x2")]
    runner = InMemoryRunner(agent=_loop(), app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id=USER, state={"tool_specs": {"specs": specs}}
    )
    await _run(runner, session.id)
    assert SEEN == [["x1", "x2"]]

    SEEN.clear()
    await _run(runner, session.id)
    assert SEEN == [], f"re-ran already-dispatched specs: {SEEN}"
