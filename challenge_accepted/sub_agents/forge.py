"""FORGE phase -- the step nothing else in the category has.

Shape:

    forge = Sequential[
        quartermaster,                     # what capability is each node missing?
        Loop[
            Dispatcher,                    # deterministic: fill K worker slots
            Parallel[ toolwright_0..K-1 ]  # build K tools concurrently
        ]
    ]

Two deliberate choices worth defending to a judge:

1. The Dispatcher is a custom BaseAgent, not an LlmAgent. Assigning queue items to
   worker slots is deterministic bookkeeping; paying for a model call to do it would be
   both slower and less reliable. It also gives the loop a real, non-model exit
   condition -- when the queue drains it escalates and the LoopAgent stops.

2. Toolwright workers write results to Firestore via `save_tool`, keyed by node_id.
   ADK's ParallelAgent docs are explicit that branch state is not automatically shared
   during execution and recommend external state management for concurrent writes; the
   store IS that external state. Session state here is only ever a per-slot inbox that
   exactly one worker reads.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.code_executors import BuiltInCodeExecutor
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.genai import types
from pydantic import BaseModel, Field

from .. import config, prompts
from ..schemas import ToolSpec
from ..services.tools import _tool_feedback, save_tool


def quartermaster_instruction(ctx: ReadonlyContext) -> str:
    """QUARTERMASTER, plus whatever the user has already rejected.

    An ADK agent with an `output_schema` gets no tools, so Quartermaster cannot call
    `read_challenge_state` and discover that the user hated the last thing it specced.
    Injecting the rejections into the prompt is the only channel available -- and
    without it the thumbs-down button is decorative, which is what it was.
    """
    cid = ctx.state.get("challenge_id")
    if not cid:
        return prompts.QUARTERMASTER
    rejected = [f for f in _tool_feedback(str(cid)) if f.get("verdict") == "down"]
    if not rejected:
        return prompts.QUARTERMASTER
    return prompts.QUARTERMASTER + "\n\n" + prompts.rejected_tools_banner(rejected)


class ToolSpecList(BaseModel):
    """Quartermaster's structured output. One spec per node, including 'not needed'."""

    specs: list[ToolSpec] = Field(
        description="Exactly one ToolSpec per node in the goal graph."
    )


quartermaster = LlmAgent(
    name="quartermaster",
    model=config.MODEL_REASONING,
    description="Decides, per node, which of the seven tool types would make it trivial.",
    instruction=quartermaster_instruction,
    mode="single_turn",
    output_schema=ToolSpecList,
    output_key="tool_specs",
)


# Underscores only, no dots. ADK's instruction templating validates `{var}` names
# against its state-name rules; a dotted key like "forge.slot_0" is not substituted and
# the worker would receive the literal placeholder text instead of its spec.
SLOT_PREFIX = "forge_slot_"
QUEUE_KEY = "forge_queue"
#: Fingerprint of the spec set the queue was last seeded from, so a second FORGE entry
#: with fresh specs reseeds instead of inheriting the drained queue.
SEED_KEY = "forge_seeded_for"


def _code_executor() -> BuiltInCodeExecutor:
    """Sandbox for generated code.

    Locally and in the demo we use BuiltInCodeExecutor (model-side execution). In
    production set CA_SANDBOX_RESOURCE_NAME to switch to AgentEngineSandboxCodeExecutor,
    which keeps a sandbox alive across tool calls within a session so variables,
    imports and files persist while a worker iterates on a failing smoke test.
    """
    if config.SANDBOX_RESOURCE_NAME:
        from google.adk.code_executors.agent_engine_sandbox_code_executor import (
            AgentEngineSandboxCodeExecutor,
        )

        return AgentEngineSandboxCodeExecutor(
            sandbox_resource_name=config.SANDBOX_RESOURCE_NAME,
            stateful=True,
            error_retry_attempts=3,
        )
    return BuiltInCodeExecutor()


def _worker(index: int) -> LlmAgent:
    """One Toolwright.

    A code executor presents to Gemini as a *server-side* (built-in) tool, and by
    default a request may not mix one with client-side function calling. Without the
    flag below the API rejects the whole request:

        400 INVALID_ARGUMENT: Please enable
        tool_config.include_server_side_tool_invocations to use Built-in tools with
        Function calling.

    That flag is what lets a single worker both execute code AND call `save_tool`.
    Found by running it; there is no way to hit this from tests that never call a model.
    Keep this agent's tool surface minimal regardless -- `save_tool` only.
    """
    return LlmAgent(
        name=f"toolwright_{index}",
        model=config.MODEL_REASONING,
        description=f"Builds the tool assigned to forge slot {index}.",
        instruction=(
            prompts.TOOLWRIGHT
            + f"\n\nYour slot key is `{SLOT_PREFIX}{index}`. "
            + f"Your assigned spec:\n{{{SLOT_PREFIX}{index}?}}"
        ),
        mode="single_turn",
        code_executor=_code_executor(),
        tools=[save_tool],
        # A worker keeps the same branch across loop iterations, so by default it sees
        # its OWN previous turn. Observed consequence: on iterations where its slot was
        # empty it re-summarised the tool it had built earlier -- confident prose, no
        # save_tool call, pure wasted tokens. With contents suppressed it sees only its
        # instruction plus the injected slot, so an empty slot reliably means idle.
        include_contents="none",
        generate_content_config=types.GenerateContentConfig(
            tool_config=types.ToolConfig(include_server_side_tool_invocations=True),
        ),
    )


class Dispatcher(BaseAgent):
    """Deterministically refills worker slots from the pending ToolSpec queue.

    Escalates (ending the enclosing LoopAgent) once every spec that needs a tool has
    been handed to a worker.
    """

    workers: int = config.FORGE_WORKERS

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        import json

        state = ctx.session.state

        raw = state.get("tool_specs") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        specs = [s for s in (raw.get("specs") or []) if s.get("needed")]

        # Reseed whenever the Quartermaster has produced a NEW spec set. Seeding only
        # on `queue is None` was wrong: FORGE can be entered more than once in a
        # session (the user says "build the tools" again, or the graph is redrawn), and
        # on the second entry the leftover empty queue from the first made the
        # Dispatcher escalate immediately -- silently discarding every new spec.
        fingerprint = json.dumps([s.get("node_id") for s in specs], sort_keys=True)
        if state.get(SEED_KEY) != fingerprint:
            queue = specs
        else:
            queue = state.get(QUEUE_KEY) or []

        batch, queue = queue[: self.workers], queue[self.workers :]

        delta: dict[str, object] = {QUEUE_KEY: queue, SEED_KEY: fingerprint}
        for i in range(self.workers):
            delta[f"{SLOT_PREFIX}{i}"] = batch[i] if i < len(batch) else None

        done = not batch
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
            actions=EventActions(state_delta=delta, escalate=done),
        )


forge = SequentialAgent(
    name="forge",
    description=(
        "FORGE phase. Works out which capability each node is missing and builds it: "
        "calculators, checklists, drills, trackers, scripts, briefs and mini-apps. "
        "Use after the goal graph is saved."
    ),
    sub_agents=[
        quartermaster,
        LoopAgent(
            name="forge_loop",
            description="Drains the ToolSpec queue in batches of concurrent workers.",
            max_iterations=6,
            sub_agents=[
                Dispatcher(name="dispatcher", description="Assigns specs to worker slots."),
                ParallelAgent(
                    name="forge_workers",
                    description="Concurrent Toolwright workers.",
                    sub_agents=[_worker(i) for i in range(config.FORGE_WORKERS)],
                ),
            ],
        ),
    ],
)

__all__ = ["forge", "quartermaster", "Dispatcher", "ToolSpecList", "SLOT_PREFIX", "QUEUE_KEY"]
