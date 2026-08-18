"""Make a turn say which agents ran and which handoffs happened.

One run in two on revision 00051 stopped dead after `save_charter`: 25-second final
turn, one tool call, zero nodes, zero specs, zero tools, and a journal ending at
"Charter locked". The Warden had not handed off to the Cartographer. There was no
error, no traceback and no log line -- the turn simply ended, and the only evidence was
an absence.

An absence is what EVERY previous version of this bug also looked like. Toolwrights
dying on a Vertex parameter looked like an absence. Workers cancelled inside a
TaskGroup looked like an absence. A second `save_charter` orphaning a challenge looked
like an absence. Each one cost hours because the first question -- "did the thing even
start?" -- had no answer anywhere.

So this answers it. Every agent entry with its BRANCH, every tool call, and one summary
line per turn naming the agents that ran and the transfers that happened. When the
chain stops early the trace shows exactly where, and when it does not, it is a few
lines.

The branch is in there because the first run this was switched on for produced the
line it was built to produce, on a different failure than the one it was built for:

    [FORGE] worker 0: START slot='baseline-5k-time-trial'
            branch=cartographer@call_636196.forge_workers.toolwright_0

FORGE was running one frame too deep. A `mode="single_turn"` sub-agent is not a
transfer target -- ADK exposes it to its parent as a TOOL and runs it in an isolated
sub-branch called `<name>@call_<n>`. Cartographer is single_turn, and the trace shows
it calling `transfer_to_agent(warden)` from inside that sub-branch instead of just
returning. So the Warden resumed INSIDE the Cartographer's tool call, handed off to
FORGE from there, and the entire FORGE loop ran under a frame that closes when the
tool call does. It closed: both workers made their second model call, neither reached
`after_agent_callback`, the loop never dispatched a second batch. 5 specs, 2 tools, no
error anywhere.

That is a hypothesis with one observation behind it, not a diagnosis -- which is
exactly why `DEEP:` is a log line and not a code change. The next run either shows the
same correlation or kills it.

**On by default.** `CA_FLOW_DEBUG=0` turns it off. That is deliberate and it is the
opposite of `CA_FORGE_DEBUG`: this failure happens on roughly half of runs, cannot be
reproduced on demand, and the flag being off is precisely the state in which it will
happen again and teach nobody anything. The cost is a handful of WARNING lines per
turn, at the level that survives the default Cloud Run config.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

FLOW_DEBUG: bool = os.getenv("CA_FLOW_DEBUG", "1") != "0"

#: ADK's own name for a handoff. A turn that should have delegated and did not is a
#: turn with none of these in it.
TRANSFER = "transfer_to_agent"

#: Traced by `sub_agents/forge.py` already, in more detail than this could add. Two
#: traces of the same eight worker entries would bury the one line that matters.
_QUIET_PREFIXES = ("toolwright_",)

#: ADK's marker for a single-turn sub-agent's isolated sub-branch: the branch reads
#: `cartographer@call_636196.forge_workers.toolwright_0` rather than
#: `forge_workers.toolwright_0`. Anything running with this in its branch is one frame
#: deeper than it should be, and dies when that frame closes.
_NESTED = "@call_"

#: invocation_id -> what happened in it. Bounded: seeded on the root agent's entry and
#: dropped on its exit, so a turn that never finishes leaves at most one entry behind.
_TURNS: dict[str, dict[str, list[str]]] = {}


def _trace(message: str) -> None:
    if FLOW_DEBUG:
        logger.warning("[FLOW] %s", message)


#: How many turns to keep. A turn is dropped when its root agent exits -- but the
#: failure being chased is a turn that ends without its root exiting cleanly, so the
#: leak this bounds is the exact case it exists to observe. Sixty-four is far more
#: than any request needs and small enough that a service under sustained failure
#: cannot grow a dict forever.
_MAX_TURNS = 64


def _evict() -> None:
    while len(_TURNS) > _MAX_TURNS:
        _TURNS.pop(next(iter(_TURNS)), None)


def _iid(ctx: Any) -> str:
    return str(getattr(ctx, "invocation_id", "?"))


def _name(ctx: Any) -> str:
    return str(getattr(ctx, "agent_name", "?"))


def _entered(callback_context: Any):
    """An agent started. MUST return None -- a Content here would skip the agent.

    That is not a hypothetical footgun: `before_agent_callback` returning content
    short-circuits the run and hands the content straight to the user, so a tracing
    callback that got sloppy about its return value would silently replace the agent
    it was supposed to be watching.
    """
    _evict()
    turn = _TURNS.setdefault(_iid(callback_context),
                             {"agents": [], "tools": [], "transfers": [], "deep": [], "flat": []})
    name = _name(callback_context)
    turn["agents"].append(name)
    branch = str(getattr(callback_context, "branch", "") or "")
    if not name.startswith(_QUIET_PREFIXES):
        _trace(f"enter {name}  branch={branch or '-'}  turn={_iid(callback_context)}")
    if _NESTED not in branch:
        # Where this agent runs when nothing has gone wrong. Recorded rather than
        # assumed, because "runs in a sub-branch" is normal -- every single-turn and
        # task agent does -- and warning on that made ten lines a turn out of a
        # signal that is one.
        if name not in turn["flat"]:
            turn["flat"].append(name)
    elif name in turn["flat"] and name not in turn["deep"]:
        turn["deep"].append(name)
        # See the module docstring: this is the shape the open bug takes. A single-turn
        # sub-agent is exposed to its parent as a TOOL and runs in an isolated
        # sub-branch named `<agent>@call_<n>`. If it hands control back with
        # `transfer_to_agent` instead of simply returning, the parent resumes INSIDE
        # that sub-branch -- and so does everything the parent does next. When the tool
        # call closes, the frame closes with it, and whatever was running underneath
        # dies without an error. Observed: FORGE's workers made their second model
        # call, never reached `after_agent_callback`, and the loop never dispatched
        # again -- 5 specs, 2 tools, no traceback anywhere.
        _trace(f"DEEP: {name} ran at the top of this turn and is now running INSIDE "
               f"{branch} -- it resumed in a child's frame instead of after it. "
               f"Whatever it starts from here dies when that frame closes.")
    return None


def _left(callback_context: Any):
    """An agent finished. On the ROOT agent this is the summary line.

    Keyed on being last rather than on the agent's name: the root is whatever ADK
    started, and hardcoding "warden" here would go quietly silent the day this file is
    reused or the root is renamed.
    """
    iid = _iid(callback_context)
    turn = _TURNS.get(iid)
    name = _name(callback_context)
    if turn is None:
        return None
    if turn["agents"] and turn["agents"][0] == name:
        state = getattr(callback_context, "state", None)
        nodes = 0
        try:
            nodes = len(state.get("node_ids") or []) if state is not None else 0
        except Exception:  # pragma: no cover - state is a mapping-ish ADK object
            nodes = 0
        ran = " -> ".join(dict.fromkeys(turn["agents"]))
        _trace(f"turn done: agents[{ran}] transfers={turn['transfers'] or 'NONE'} "
               f"nodes={nodes} tools={turn['tools']} "
               f"deep={turn['deep'] or 'none'}")
        if not turn["transfers"] and len(set(turn["agents"])) == 1:
            # The exact shape of the open bug: the root answered by itself. Said out
            # loud so it can be grepped for, rather than inferred later from what is
            # missing three lines up.
            _trace(f"NO HANDOFF: {name} finished the turn alone. If the user asked for "
                   f"work a sub-agent owns, this is the failure -- not whatever the "
                   f"sub-agent did or did not build.")
        _TURNS.pop(iid, None)
    elif not name.startswith(_QUIET_PREFIXES):
        _trace(f"leave {name}")
    return None


def _tool_called(tool: Any, args: dict, tool_context: Any):
    """A tool call. MUST return None -- a dict here REPLACES the tool's result."""
    turn = _TURNS.setdefault(_iid(tool_context),
                             {"agents": [], "tools": [], "transfers": [], "deep": [], "flat": []})
    name = str(getattr(tool, "name", tool))
    if name == TRANSFER:
        target = str((args or {}).get("agent_name") or "?")
        turn["transfers"].append(target)
        _trace(f"handoff -> {target}")
    else:
        turn["tools"].append(name)
    return None


def _chain(existing: Any, added: Callable) -> Any:
    """Ours first, then whatever the agent already had.

    ADK calls a list of callbacks in order **until one returns non-None**, and every
    callback here returns None on purpose, so nothing downstream is skipped. Same
    shape as `vertex_compat._chain`; kept separate because that one is about
    correctness and this one is about visibility, and merging them would mean turning
    off tracing to turn off a crash guard.
    """
    if existing is None:
        return added
    if isinstance(existing, list):
        return [added, *existing]
    return [added, existing]


def install(agent: Any, _seen: set[int] | None = None) -> int:
    """Attach the trace to every agent reachable from `agent`.

    Returns how many were touched so the caller can assert it is not zero -- a silent
    no-op would leave the next unreproducible failure exactly as unreadable as this
    one was.
    """
    seen = _seen if _seen is not None else set()
    if agent is None or id(agent) in seen:
        return 0
    seen.add(id(agent))

    touched = 0
    if hasattr(agent, "before_agent_callback"):
        agent.before_agent_callback = _chain(
            getattr(agent, "before_agent_callback", None), _entered)
        agent.after_agent_callback = _chain(
            getattr(agent, "after_agent_callback", None), _left)
        touched += 1
    if hasattr(agent, "before_tool_callback"):
        agent.before_tool_callback = _chain(
            getattr(agent, "before_tool_callback", None), _tool_called)

    for sub in getattr(agent, "sub_agents", None) or []:
        touched += install(sub, seen)

    for tool in getattr(agent, "tools", None) or []:
        inner = getattr(tool, "agent", None)
        if inner is not None:
            touched += install(inner, seen)

    return touched
