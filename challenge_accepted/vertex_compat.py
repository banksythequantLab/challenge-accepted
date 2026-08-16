"""One incompatibility between Vertex and the Developer API, applied everywhere.

`executable_code` and `code_execution_result` parts come back from Gemini carrying an
`id`. Sent back on the Developer API that is fine; on Vertex, `google-genai` raises
rather than dropping it:

    ValueError: id parameter is only supported in Gemini Developer API mode, not in
    Gemini Enterprise Agent Platform mode.
      google/genai/models.py:1188  in _ExecutableCode_to_vertex
      google/genai/models.py:224   in _CodeExecutionResult_to_vertex

Those are the only two converters in the library that raise it -- checked, not assumed.

This lived on the Toolwrights, because they are the agents that execute code. That was
the wrong scope, and the reason it came back:

**The root agent has no branch.** ADK segregates history per agent by comparing branch
paths, but `_is_event_belongs_to_branch` opens with

    if not invocation_branch or not event.branch:
        return True

and the root agent's invocation branch is `None`. So Warden does not get a filtered
view of the conversation -- it gets *everything*, including the four Toolwrights'
`executableCode` events from deep inside FORGE. Every one of those carries an `id`.
The next time Warden spoke after a build, its own request contained parts that Vertex
refuses, and the turn died at the very end:

    runners.py:610      _drive_root_node
    _llm_agent_wrapper.py:370  run_llm_agent_as_node      <- the ROOT agent
    google_llm.py:282   generate_content_async
    models.py:1188      _ExecutableCode_to_vertex         -> ValueError

which is why the failure was attributed to `warden` and why it appeared only after a
FORGE turn, long after the Toolwrights themselves had finished cleanly.

The fix is not a cleverer callback -- it is the same callback on every agent that can
ever see history. `install()` walks the tree so a new agent inherits it without anyone
remembering to.
"""

from __future__ import annotations

from typing import Any, Callable

from . import config

#: The two part types whose `id` Vertex rejects.
_CODE_PARTS = ("executable_code", "code_execution_result")


def strip_code_ids(callback_context: Any, llm_request: Any) -> None:
    """Drop ids Vertex will not accept. A no-op on the Developer API.

    Returns None so ADK carries on with the (now mutated) request.
    """
    if not config.use_vertex_models():
        return None
    for content in getattr(llm_request, "contents", None) or []:
        for part in getattr(content, "parts", None) or []:
            for attr in _CODE_PARTS:
                blob = getattr(part, attr, None)
                if blob is not None and getattr(blob, "id", None) is not None:
                    blob.id = None
    return None


def _chain(existing: Any, added: Callable) -> Any:
    """Run ours first, then whatever the agent already had.

    Ours only deletes a field, so it cannot change what an existing callback sees --
    except by removing the thing that would have crashed the call.
    """
    if existing is None:
        return added
    if isinstance(existing, list):
        return [added, *existing]
    return [added, existing]


def install(agent: Any, _seen: set[int] | None = None) -> int:
    """Attach `strip_code_ids` to every agent reachable from `agent`.

    Walks `sub_agents` and any `AgentTool`-wrapped agent, because an AgentTool runs its
    agent as a root -- which is exactly the unbranched case that caused this.

    Returns how many agents were touched, so a caller can assert it is not zero. A
    silent no-op here would restore the original bug and look like nothing happened.
    """
    seen = _seen if _seen is not None else set()
    if agent is None or id(agent) in seen:
        return 0
    seen.add(id(agent))

    touched = 0
    if hasattr(agent, "before_model_callback"):
        agent.before_model_callback = _chain(
            getattr(agent, "before_model_callback", None), strip_code_ids)
        touched += 1

    for sub in getattr(agent, "sub_agents", None) or []:
        touched += install(sub, seen)

    for tool in getattr(agent, "tools", None) or []:
        inner = getattr(tool, "agent", None)
        if inner is not None:
            touched += install(inner, seen)

    return touched
