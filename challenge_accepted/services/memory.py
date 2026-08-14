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
import os
import time
from typing import Any

from google.adk.tools import _memory_entry_utils
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

logger = logging.getLogger(__name__)

# --- the negative cache ------------------------------------------------------
#
# Measured against the live Agent Engine: a `search_memory` for a user with no
# memories takes a **median of 1810 ms** (n=6, min 1655, max 2344) and returns
# nothing. `preload_memory` runs on every LLM request for Warden and the
# Interviewer, so a first-time user -- every judge, every demo -- pays that on
# every turn of a nine-question interview to be told, repeatedly, that they have
# no past.
#
# "This user has no memories" is the one search result that does not depend on
# the query, so it is the one result safe to cache. Positive hits are never
# cached: those are semantic matches against what the user just typed, and
# serving turn one's matches on turn four would quietly make recall worse to
# save time.

#: app/user -> the moment we should stop believing they are empty.
_EMPTY_UNTIL: dict[str, float] = {}

#: Short by design. The cost of being wrong is one turn without recall; the cost
#: of a long TTL is a user whose first saved charter is invisible until it
#: expires. `remember_session` clears the entry on write, so this only covers
#: memories created outside this process.
EMPTY_TTL_S: float = float(os.getenv("CA_MEMORY_EMPTY_TTL", "300"))


def _key(app_name: str, user_id: str) -> str:
    return f"{app_name}/{user_id}"


def mark_empty(app_name: str, user_id: str) -> None:
    _EMPTY_UNTIL[_key(app_name, user_id)] = time.monotonic() + EMPTY_TTL_S


def looks_empty(app_name: str, user_id: str) -> bool:
    until = _EMPTY_UNTIL.get(_key(app_name, user_id))
    if until is None:
        return False
    if time.monotonic() >= until:
        _EMPTY_UNTIL.pop(_key(app_name, user_id), None)
        return False
    return True


def forget_empty(app_name: str, user_id: str) -> None:
    """Called the moment we write, so the next turn searches for real."""
    _EMPTY_UNTIL.pop(_key(app_name, user_id), None)


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

    # They have a past now. Anything cached saying otherwise is stale.
    session = getattr(tool_context, "session", None)
    app_name = getattr(session, "app_name", None)
    user_id = getattr(tool_context, "user_id", None)
    if app_name and user_id:
        forget_empty(str(app_name), str(user_id))
    return True


class PreloadMemory(PreloadMemoryTool):
    """ADK's `preload_memory`, minus the 1.8s it spends re-proving a new user has no past.

    Behaviour is identical on every path that matters. The only change: once a search
    for a given user comes back empty we remember that for `EMPTY_TTL_S` and skip the
    round trip, and we drop that the instant `remember_session` writes something.

    The search-and-inject body is a copy of ADK 2.6.3's, not a call to it, because the
    upstream method returns `None` whether it found nothing or found plenty -- there is
    no way to learn "empty" by delegating. That copy leans on
    `LlmRequest._append_dynamic_instructions`, which is private. `tests/test_memory.py`
    asserts the method still exists, so an ADK upgrade that renames it fails in the test
    suite rather than silently dropping every memory injection in production, which is
    precisely how a feature becomes decorative without anyone noticing.
    """

    async def process_llm_request(self, *, tool_context, llm_request) -> None:  # type: ignore[override]
        user_content = tool_context.user_content
        if not user_content or not user_content.parts or not user_content.parts[0].text:
            return

        app_name = str(getattr(getattr(tool_context, "session", None), "app_name", ""))
        user_id = str(getattr(tool_context, "user_id", ""))
        if app_name and user_id and looks_empty(app_name, user_id):
            return

        try:
            response = await tool_context.search_memory(user_content.parts[0].text)
        except Exception:  # noqa: BLE001 -- a memory outage degrades the prompt, never the turn
            logger.warning("memory: preload search failed")
            return

        if not response.memories:
            if app_name and user_id:
                mark_empty(app_name, user_id)
            return

        lines: list[str] = []
        for memory in response.memories:
            if memory.timestamp:
                lines.append(f"Time: {memory.timestamp}")
            if text := _memory_entry_utils.extract_text(memory):
                lines.append(f"{memory.author}: {text}" if memory.author else text)
        if not lines:
            return

        llm_request._append_dynamic_instructions([
            "The following content is from your previous conversations with the user.\n"
            "They may be useful for answering the user's current query.\n"
            "<PAST_CONVERSATIONS>\n" + "\n".join(lines) + "\n</PAST_CONVERSATIONS>\n"
        ])


#: One instance, wired onto Warden and the Interviewer.
preload_memory = PreloadMemory()


__all__ = ["remember_session", "preload_memory", "PreloadMemory",
           "mark_empty", "looks_empty", "forget_empty", "EMPTY_TTL_S"]
