"""The write side of Vertex AI Memory Bank, and an honest note about its scope.

Memory Bank is scoped to `(app_name, user_id)`. That makes it *personal* recall across
challenges -- "last time you tried this you stalled on the permit office" -- and not the
party's shared notebook. The shared notebook is `remember_group_fact`, which writes to
Firestore `groups/{id}.shared_facts` and is read back wholesale by
`read_challenge_state`. The two look alike in a diagram and are not the same thing, and
saying otherwise would promise a teammate a memory they do not actually share.

Reading needs no code here: ADK's `preload_memory` tool runs on every LLM request,
searches memory with the user's own words, and injects any hits as dynamic
instructions. Writing has no such hook, so we call it at the two moments a durable fact
exists -- the charter is saved, and a node is closed with evidence. Ingesting on every
turn would send the whole session back for re-consolidation after turns that decided
nothing.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def remember_session(tool_context: Any) -> bool:
    """Hand the current session to the memory service. Best effort, never fatal.

    Returns True when a memory service accepted the session.

    Failure is swallowed on purpose, and the reason is worth stating: this is called
    from inside `save_charter` and `complete_node`. If Memory Bank is unreachable, or
    no memory service is configured at all -- which is every local run and every test --
    the right outcome is that the charter still saves and the node still closes. A
    charter that fails because a nice-to-have recall layer had a bad minute is a worse
    product than one that quietly remembers less.

    ADK's own `PreloadMemoryTool` takes the same position on the read side: it catches
    every exception out of `search_memory` and returns, so a memory outage degrades the
    prompt instead of breaking the turn.
    """
    add = getattr(tool_context, "add_session_to_memory", None)
    if add is None:
        # A test double, or a context predating ADK's memory API.
        return False
    try:
        await add()
    except Exception as exc:  # noqa: BLE001 -- see docstring
        logger.info("memory: session not stored (%s: %s)", type(exc).__name__, exc)
        return False
    return True


__all__ = ["remember_session"]
