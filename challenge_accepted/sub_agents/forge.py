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

import logging
import os
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


logger = logging.getLogger(__name__)

#: FORGE is the one phase whose failures are invisible: a worker that does nothing looks
#: exactly like a worker with nothing to do, and the dashboard renders identically either
#: way. Six specs became one tool on the deployed service with no error anywhere. Set
#: `CA_FORGE_DEBUG=1` and the phase narrates itself into Cloud Logging at WARNING, which
#: is the level that survives the default Cloud Run config.
FORGE_DEBUG: bool = os.getenv("CA_FORGE_DEBUG", "0") == "1"


def _trace(message: str) -> None:
    if FORGE_DEBUG:
        logger.warning("[FORGE] %s", message)


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


def _worker_config() -> types.GenerateContentConfig:
    """`include_server_side_tool_invocations`, but only where it is legal.

    Vertex raises on the parameter itself, so it cannot be set-and-ignored -- it has to
    be absent. `config.use_vertex_models()` reads the same `GOOGLE_GENAI_USE_VERTEXAI`
    the genai client uses to choose its mode, so the two cannot disagree.
    """
    if config.use_vertex_models():
        return types.GenerateContentConfig()
    return types.GenerateContentConfig(
        tool_config=types.ToolConfig(include_server_side_tool_invocations=True),
    )


def _strip_code_ids(callback_context, llm_request):
    """Remove the `id` Vertex refuses to accept back on code parts.

    The bug this fixes killed FORGE on every deployed revision, and it hid behind the
    first one. A Toolwright's first model call succeeds and comes back with an
    `executableCode` part carrying an `id`. ADK keeps that part in the agent's history.
    The worker's *second* call sends the history back, and `google-genai` refuses to
    convert it:

        ValueError: id parameter is only supported in Gemini Developer API mode, not in
        Gemini Enterprise Agent Platform mode.
          File "google/genai/models.py", line 1188, in _ExecutableCode_to_vertex

    `_CodeExecutionResult_to_vertex` has the identical guard, so both part types matter.

    Why exactly one tool got built, every time: the workers run inside an
    `asyncio.TaskGroup`, where one failure cancels its siblings. Whichever worker
    reached a second model call first raised, and took the other three down with it
    mid-build. The trace makes it unambiguous -- four workers START with four distinct
    specs, one saves, none reach END, the loop never runs a second iteration, and the
    dashboard shows a finished-looking challenge with one tool.

    Nothing about that is visible from outside, which is why it survived weeks of green
    deploys: no worker logs an error, ADK folds the sub-exception into an
    `ExceptionGroup`, and a phase that builds one of seven tools renders exactly like a
    phase that only needed one.
    """
    # Traced per model call, because "the worker idled" has three very different
    # causes and they are indistinguishable from outside: no model call at all (ADK
    # never ran the flow), a call whose instruction lost its spec (state injection),
    # or a call that saw the spec and chose to do nothing (the prompt). Iteration two
    # of the loop builds nothing and this says which.
    if FORGE_DEBUG:
        instruction = ""
        for part in (getattr(llm_request, "config", None) and
                     getattr(llm_request.config, "system_instruction", None)) or []:
            instruction += getattr(part, "text", "") or ""
        if isinstance(getattr(getattr(llm_request, "config", None),
                              "system_instruction", None), str):
            instruction = llm_request.config.system_instruction
        _trace(f"model call: agent={getattr(callback_context, 'agent_name', '?')} "
               f"spec_in_prompt={'node_id' in instruction} "
               f"instr_chars={len(instruction)} contents={len(llm_request.contents or [])}")

    if not config.use_vertex_models():
        return None
    stripped = 0
    for content in llm_request.contents or []:
        for part in getattr(content, "parts", None) or []:
            for attr in ("executable_code", "code_execution_result"):
                blob = getattr(part, attr, None)
                if blob is not None and getattr(blob, "id", None) is not None:
                    blob.id = None
                    stripped += 1
    if stripped:
        _trace(f"stripped {stripped} code-part id(s) Vertex would have rejected")
    return None


def _saw_its_slot(index: int):
    """Did this worker start, and was there anything in its inbox when it did?

    An idle worker and a broken worker produce the same output: nothing. This is the
    only place that can tell them apart, because it runs before the model does.
    """

    def _cb(callback_context):
        if not FORGE_DEBUG:
            return None
        slot = callback_context.state.get(f"{SLOT_PREFIX}{index}")
        node = slot.get("node_id") if isinstance(slot, dict) else slot
        _trace(f"worker {index}: START slot={'EMPTY' if slot is None else node!r} "
               f"branch={getattr(callback_context, 'branch', '?')}")
        return None

    return _cb


def _finished(index: int):
    def _cb(callback_context):
        if not FORGE_DEBUG:
            return None
        _trace(f"worker {index}: END")
        return None

    return _cb


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

    **And it is only legal on the Gemini Developer API.** Sending it to Vertex fails:

        ValueError: include_server_side_tool_invocations parameter is only supported in
        Gemini Developer API mode, not in Gemini Enterprise Agent Platform mode.

    Local runs use a `GOOGLE_API_KEY` (Developer API) and need the flag. The deployed
    service sets `GOOGLE_GENAI_USE_VERTEXAI=TRUE` and is destroyed by it. So the fix for
    one environment was, unnoticed, the outage in the other: **every Toolwright on every
    deployed revision died**, and the goal graph, journal, party and dashboard all
    carried on looking perfect around the hole. Ten challenges in production Firestore,
    every agent-driven one with `tools: []`, while local runs built four to six every
    time and the README recorded that as verified.

    Nothing surfaced it because the failure is invisible from every direction we were
    looking: the deploy succeeds, `/api/healthz` is green, the UI renders, the FORGE
    rail animates, and the tool count nobody was asserting on is zero.
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
        generate_content_config=_worker_config(),
        before_agent_callback=_saw_its_slot(index),
        after_agent_callback=_finished(index),
        # Runs on EVERY model call, including the second one inside a single build --
        # which is the one that was killing the phase. See `_strip_code_ids`.
        before_model_callback=_strip_code_ids,
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
        _trace(
            f"dispatch: specs={len(specs)} batch={len(batch)} remaining={len(queue)} "
            f"escalate={done} reseed={state.get(SEED_KEY) != fingerprint} "
            f"slots={[ (batch[i].get('node_id') if i < len(batch) else None) for i in range(self.workers) ]}"
        )
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
