"""Does the FORGE loop actually drain the queue, or stop after one batch?

A live run produced exactly 4 tools for 10 nodes -- and FORGE_WORKERS is 4. That is
either a coincidence or the loop only ever running once. This answers it without
spending a token: the real Dispatcher and the real LoopAgent, with a stub standing in
for the Toolwright workers that just records which specs it was handed.
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
from google.adk.agents import BaseAgent, LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from challenge_accepted.sub_agents.forge import (
    QUEUE_KEY,
    SEED_KEY,
    SLOT_PREFIX,
    Dispatcher,
)

APP = "forge_loop_test"
USER = "u1"

SEEN: list[list[str]] = []


class RecordingWorkers(BaseAgent):
    """Stands in for ParallelAgent[toolwright_0..3]; records each batch it receives."""

    workers: int = 4

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        batch = []
        for i in range(self.workers):
            spec = ctx.session.state.get(f"{SLOT_PREFIX}{i}")
            if spec:
                batch.append(spec["node_id"])
        SEEN.append(batch)
        yield Event(author=self.name, invocation_id=ctx.invocation_id, branch=ctx.branch)


def _spec(node_id: str) -> dict:
    return {"node_id": node_id, "needed": True, "tool_type": "calculator",
            "name": node_id, "purpose": "p", "inputs": [], "outputs": [],
            "smoke_test": "x"}


@pytest.mark.asyncio
async def test_loop_drains_the_whole_queue():
    SEEN.clear()
    specs = [_spec(f"n{i}") for i in range(10)]

    loop = LoopAgent(
        name="forge_loop",
        description="test",
        max_iterations=6,
        sub_agents=[
            Dispatcher(name="dispatcher", description="d"),
            RecordingWorkers(name="workers", description="w"),
        ],
    )
    runner = InMemoryRunner(agent=loop, app_name=APP)
    session = await runner.session_service.create_session(
        app_name=APP, user_id=USER, state={"tool_specs": {"specs": specs}}
    )
    async for _ in runner.run_async(
        user_id=USER, session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="go")]),
    ):
        pass

    dispatched = [nid for batch in SEEN for nid in batch]
    final = await runner.session_service.get_session(
        app_name=APP, user_id=USER, session_id=session.id
    )

    print(f"\nbatches: {SEEN}")
    print(f"queue remaining: {final.state.get(QUEUE_KEY)}")

    assert dispatched == [f"n{i}" for i in range(10)], (
        f"Only {len(dispatched)} of 10 specs were dispatched across {len(SEEN)} "
        f"batch(es): {SEEN}"
    )
    assert final.state.get(QUEUE_KEY) == []
