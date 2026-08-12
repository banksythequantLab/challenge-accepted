"""A session service backed by the same Firestore everything else uses.

WHY THIS EXISTS

With `session_service_uri=None`, ADK does not use an in-memory service -- it falls back
to per-agent local SQLite under `<agents_dir>/<agent>/.adk/`. That is fine on a laptop
and wrong on Cloud Run in two ways that both bite during a seven-week judging window:

  1. The filesystem is per-instance and ephemeral. `max-instances=10` and no session
     affinity means a judge's second message can land on an instance that has never
     heard of their session. The dashboard notices and rebuilds it, so nothing errors
     -- the conversation history simply vanishes and the Interviewer starts over. A
     silent amnesia is worse than a visible failure.
  2. A new revision, or any instance recycle, loses every in-flight conversation.

Firestore is already the source of truth for challenges, nodes, tools, journal, groups
and feedback. Sessions were the one thing living somewhere else, which is exactly the
kind of inconsistency that only shows up in production.

SHAPE

    /sessions/{app|user|sid}          metadata + state + event count
    /session_events/{app|user|sid|n}  one document per event, ordered by n

Events go in their own collection rather than an array on the session document, for a
concrete reason: Firestore caps a document at 1 MiB, and a FORGE turn with executable
code and its output can produce a few hundred KB of events by itself. Appending to an
array also means rewriting the whole document on every event, which is O(n^2) bytes
written over a conversation. One document per event is O(1) per append and has no
practical ceiling.

Registered under the `firestore://` scheme through ADK's own service registry, so
`get_fast_api_app(session_service_uri=...)` picks it up the documented way rather than
by monkey-patching.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from google.adk.events import Event
from google.adk.sessions import Session
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.state import State

from .store import Store, new_id, store as default_store

logger = logging.getLogger(__name__)

SESSIONS = "sessions"
EVENTS = "session_events"

#: Firestore document ids may not contain "/". Everything else is fair game, and the
#: parts are ids we generate, so a simple separator is safe.
SEP = "|"


def _key(app_name: str, user_id: str, session_id: str) -> str:
    return f"{app_name}{SEP}{user_id}{SEP}{session_id}"


def _persistable(state: dict[str, Any]) -> dict[str, Any]:
    """State minus the temp-scoped keys.

    The base class deliberately writes `temp:` keys into the LIVE session state so that
    later agents in the same invocation can read them, and strips them only from the
    event's delta. So persisting `session.state` wholesale writes them to storage
    anyway -- and they come back on the next turn, which is the exact opposite of what
    "temp" means. A test caught this; it is not obvious from the interface.
    """
    return {k: v for k, v in state.items() if not k.startswith(State.TEMP_PREFIX)}


class FirestoreSessionService(BaseSessionService):
    """Sessions and their events, in Firestore.

    Takes the same `Store` the rest of the app uses, so it inherits the in-memory
    fallback for free: with no GOOGLE_CLOUD_PROJECT the tests and the local dev server
    exercise exactly this code path against a dict.
    """

    def __init__(self, store: Optional[Store] = None, **_ignored: Any) -> None:
        # The service registry passes `agents_dir` and friends. We do not need them,
        # but swallowing unknown kwargs keeps us compatible when ADK adds more.
        self._store = store or default_store

    # -- helpers -------------------------------------------------------------

    async def _read(self, collection: str, doc_id: str) -> Optional[dict[str, Any]]:
        # The Firestore client is synchronous. Calling it directly from an async
        # handler blocks the event loop, which on Cloud Run means one slow read stalls
        # every other request on that instance.
        return await asyncio.to_thread(self._store.get, collection, doc_id)

    async def _write(self, collection: str, doc_id: str, doc: dict[str, Any]) -> None:
        await asyncio.to_thread(self._store._put, collection, doc_id, doc)

    async def _events_for(self, skey: str) -> list[Event]:
        rows = await asyncio.to_thread(self._store._query, EVENTS, "session_key", skey)
        rows.sort(key=lambda r: r.get("n", 0))
        out: list[Event] = []
        for r in rows:
            try:
                out.append(Event.model_validate(r["event"]))
            except Exception:  # noqa: BLE001
                # One malformed event must not make the whole conversation unreadable.
                # Dropping it loses a turn; raising loses the session.
                logger.warning("Skipping unreadable event %s in session %s",
                               r.get("n"), skey)
        return out

    # -- BaseSessionService --------------------------------------------------

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        sid = session_id or new_id("s_")
        session = Session(
            id=sid,
            app_name=app_name,
            user_id=user_id,
            state=dict(state or {}),
            events=[],
            last_update_time=time.time(),
        )
        await self._write(SESSIONS, _key(app_name, user_id, sid), {
            "id": sid,
            "app_name": app_name,
            "user_id": user_id,
            "state": _persistable(session.state),
            "n_events": 0,
            "last_update_time": session.last_update_time,
        })
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        skey = _key(app_name, user_id, session_id)
        doc = await self._read(SESSIONS, skey)
        if not doc:
            return None

        events = await self._events_for(skey)
        if config:
            if config.after_timestamp:
                events = [e for e in events
                          if (e.timestamp or 0) >= config.after_timestamp]
            if config.num_recent_events:
                events = events[-config.num_recent_events:]

        return Session(
            id=doc.get("id", session_id),
            app_name=doc.get("app_name", app_name),
            user_id=doc.get("user_id", user_id),
            state=doc.get("state") or {},
            events=events,
            last_update_time=doc.get("last_update_time") or 0.0,
        )

    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> ListSessionsResponse:
        rows = await asyncio.to_thread(
            self._store._query, SESSIONS, "app_name", app_name)
        if user_id is not None:
            rows = [r for r in rows if r.get("user_id") == user_id]
        rows.sort(key=lambda r: r.get("last_update_time") or 0.0, reverse=True)
        # Deliberately WITHOUT events. ADK's own services do the same, and the session
        # list endpoint is polled -- loading every event of every session to render a
        # list would make the picker quadratic in conversation length.
        return ListSessionsResponse(sessions=[
            Session(
                id=r.get("id", ""),
                app_name=r.get("app_name", app_name),
                user_id=r.get("user_id", ""),
                state=r.get("state") or {},
                events=[],
                last_update_time=r.get("last_update_time") or 0.0,
            )
            for r in rows
        ])

    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        skey = _key(app_name, user_id, session_id)
        await asyncio.to_thread(self._store.delete, SESSIONS, skey)
        await asyncio.to_thread(self._store.delete_where, EVENTS, "session_key", skey)

    async def append_event(self, session: Session, event: Event) -> Event:
        """Persist one event.

        THE STORE CALLS BELOW ARE DELIBERATELY SYNCHRONOUS. Do not "improve" them to
        `asyncio.to_thread`.

        The first version did exactly that, for the obvious reason: the Firestore
        client is blocking, and blocking the event loop on Cloud Run means one slow
        write stalls every other request on the instance. It passed all 91 unit tests
        and every browser check except the one that drives a real FORGE turn -- which
        died mid-stream with ERR_INCOMPLETE_CHUNKED_ENCODING, an ASGI exception group
        terminating in GeneratorExit, and a pile of "Failed to detach context" from
        OpenTelemetry.

        The cause: ADK runs agents as nested async generators wrapped in `Aclosing`,
        and `append_event` is called from inside them. Introducing a real suspension
        point there -- a thread hop is one -- lets the loop interleave teardown with
        the write, and the generator gets closed under it. The user sees the agents
        stop halfway through building their tools.

        So the trade is explicit: a Firestore write (tens of milliseconds) blocks the
        loop, once per event. At demo and judging scale that is fine. At real scale
        the fix is a background writer drained in `flush()`, NOT an await here.

        Reads are a different story -- `get_session` and `list_sessions` are called
        from ordinary request handlers, not from inside a generator, so they keep
        their thread hop.
        """
        # The base class applies the state delta to the live session and drops partial
        # events. Let it, then persist what it decided -- reimplementing that merge is
        # how the two copies drift apart.
        event = await super().append_event(session, event)
        if event.partial:
            return event

        skey = _key(session.app_name, session.user_id, session.id)
        n = len(session.events) - 1
        self._store._put(EVENTS, f"{skey}{SEP}{n:06d}", {
            "session_key": skey,
            "n": n,
            "event": event.model_dump(mode="json", exclude_none=True),
        })
        session.last_update_time = time.time()
        # A FULL WRITE, not a merge. Firestore's set(merge=True) deep-merges map
        # fields, so a key a later turn removed from state would linger forever -- but
        # the in-memory stub's dict.update() replaces `state` wholesale. The two
        # backends would then disagree about what the session contains, and only the
        # one nobody tests locally would be wrong. Writing the whole document makes
        # them identical.
        self._store._put(SESSIONS, skey, {
            "id": session.id,
            "app_name": session.app_name,
            "user_id": session.user_id,
            "state": _persistable(session.state),
            "n_events": len(session.events),
            "last_update_time": session.last_update_time,
        })
        return event


def register() -> None:
    """Teach ADK the `firestore://` session scheme.

    Idempotent -- importing this module twice (which happens under uvicorn reload)
    must not raise.
    """
    from google.adk.cli.service_registry import get_service_registry

    get_service_registry().register_session_service(
        "firestore", lambda uri, **kwargs: FirestoreSessionService(**kwargs)
    )
