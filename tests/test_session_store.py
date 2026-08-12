"""Conversations have to survive the instance they started on.

ADK's default with `session_service_uri=None` is per-agent SQLite under
`<agents_dir>/<agent>/.adk/`. On Cloud Run that file is per-instance and ephemeral, and
we run with `max-instances=10` and no session affinity -- so a judge's second message
can land on an instance that has never heard of their session. The dashboard notices a
missing session and rebuilds it, which means nothing errors and the conversation
history simply disappears mid-interview.

The test that matters is therefore not "can I read back what I just wrote" -- an
in-memory dict passes that. It is "can a DIFFERENT service instance, holding no state
of its own, read a conversation the first one wrote". That is what an instance swap
looks like from the outside.
"""

from __future__ import annotations

import asyncio

import pytest
from google.adk.events import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from challenge_accepted.services.session_store import FirestoreSessionService
from challenge_accepted.services.store import Store

APP = "challenge_accepted"


def _svc(store: Store) -> FirestoreSessionService:
    return FirestoreSessionService(store=store)


def _say(author: str, text: str, **actions) -> Event:
    # `actions` is not Optional on Event -- passing None is a validation error, not a
    # convenient default.
    return Event(
        author=author,
        content=types.Content(role="user" if author == "user" else "model",
                              parts=[types.Part(text=text)]),
        actions=EventActions(**actions),
    )


def run(coro):
    return asyncio.run(coro)


def test_a_second_instance_reads_a_conversation_the_first_one_wrote():
    """The whole point. Two services, one store, no shared memory."""
    shared = Store()          # stands in for Firestore
    instance_a = _svc(shared)
    instance_b = _svc(shared)  # a different Cloud Run instance, cold

    async def scenario():
        s = await instance_a.create_session(
            app_name=APP, user_id="u_derek",
            state={"user_id": "u_derek", "group_id": "grp_team"},
            session_id="s_live",
        )
        await instance_a.append_event(s, _say("user", "I want to run a 10k."))
        await instance_a.append_event(s, _say("interviewer", "By when?"))
        await instance_a.append_event(s, _say("user", "By Christmas."))

        return await instance_b.get_session(
            app_name=APP, user_id="u_derek", session_id="s_live")

    got = run(scenario())

    assert got is not None, "the second instance could not find the session at all"
    assert [e.content.parts[0].text for e in got.events] == [
        "I want to run a 10k.", "By when?", "By Christmas."
    ]
    assert got.state["group_id"] == "grp_team"


def test_events_come_back_in_order_even_past_ten():
    """Ids are string-sorted somewhere in the chain; 10 must not land before 2."""
    shared = Store()

    async def scenario():
        s = await _svc(shared).create_session(
            app_name=APP, user_id="u", session_id="s_many")
        writer = _svc(shared)
        for i in range(15):
            await writer.append_event(s, _say("user", f"turn {i}"))
        return await _svc(shared).get_session(
            app_name=APP, user_id="u", session_id="s_many")

    got = run(scenario())
    assert [e.content.parts[0].text for e in got.events] == [
        f"turn {i}" for i in range(15)
    ]


def test_state_written_by_a_tool_survives_the_hop():
    """save_charter writes challenge_id into state. If that does not persist, the next
    instance re-interviews the user about a goal that already exists."""
    shared = Store()

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id="u", session_id="s_state")
        await a.append_event(
            s, _say("warden", "Charter locked.",
                    state_delta={"challenge_id": "chal_abc", "group_id": "grp_team"}))
        return await _svc(shared).get_session(
            app_name=APP, user_id="u", session_id="s_state")

    got = run(scenario())
    assert got.state["challenge_id"] == "chal_abc"
    assert got.state["group_id"] == "grp_team"


def test_partial_events_are_not_persisted():
    """Streaming emits a partial per chunk. Storing them would multiply a conversation
    by its token count and replay the answer in fragments on the next instance."""
    shared = Store()

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id="u", session_id="s_partial")
        chunk = _say("coach", "Here is ")
        chunk.partial = True
        await a.append_event(s, chunk)
        await a.append_event(s, _say("coach", "Here is what done looks like."))
        return await _svc(shared).get_session(
            app_name=APP, user_id="u", session_id="s_partial")

    got = run(scenario())
    assert [e.content.parts[0].text for e in got.events] == [
        "Here is what done looks like."
    ]


def test_temp_state_does_not_leak_into_storage():
    """`temp:` keys are per-invocation by contract. Persisting them would resurrect
    scratch values on a later turn."""
    shared = Store()

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id="u", session_id="s_temp")
        await a.append_event(
            s, _say("warden", "working",
                    state_delta={"temp:scratch": "ignore me", "keep": "this"}))
        return await _svc(shared).get_session(
            app_name=APP, user_id="u", session_id="s_temp")

    got = run(scenario())
    assert got.state.get("keep") == "this"
    assert "temp:scratch" not in got.state


def test_a_missing_session_is_none_not_an_exception():
    """The dashboard relies on a 404 to know it should rebuild. An exception here would
    surface as a 500 and the retry path would never run."""
    got = run(_svc(Store()).get_session(app_name=APP, user_id="u", session_id="nope"))
    assert got is None


def test_deleting_a_session_takes_its_events_with_it():
    """Otherwise every deleted conversation leaves its events behind forever, and the
    next session that reuses the id inherits a stranger's history."""
    shared = Store()

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id="u", session_id="s_gone")
        for i in range(3):
            await a.append_event(s, _say("user", f"m{i}"))
        await a.delete_session(app_name=APP, user_id="u", session_id="s_gone")
        return await a.get_session(app_name=APP, user_id="u", session_id="s_gone")

    assert run(scenario()) is None
    assert shared._query("session_events", "session_key", f"{APP}|u|s_gone") == []


def test_sessions_do_not_leak_between_users():
    shared = Store()

    async def scenario():
        a = _svc(shared)
        await a.create_session(app_name=APP, user_id="u_derek", session_id="s1")
        await a.create_session(app_name=APP, user_id="u_dana", session_id="s2")
        mine = await a.list_sessions(app_name=APP, user_id="u_derek")
        return [s.id for s in mine.sessions]

    assert run(scenario()) == ["s1"]


def test_listing_sessions_does_not_load_their_events():
    """The session list is polled. Loading every event of every session to render a
    list is quadratic in conversation length."""
    shared = Store()

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id="u", session_id="s_big")
        for i in range(5):
            await a.append_event(s, _say("user", f"m{i}"))
        return await a.list_sessions(app_name=APP)

    listed = run(scenario())
    assert [s.id for s in listed.sessions] == ["s_big"]
    assert listed.sessions[0].events == []


def test_the_recent_events_window_is_honoured():
    shared = Store()
    from google.adk.sessions.base_session_service import GetSessionConfig

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id="u", session_id="s_win")
        for i in range(10):
            await a.append_event(s, _say("user", f"m{i}"))
        return await a.get_session(
            app_name=APP, user_id="u", session_id="s_win",
            config=GetSessionConfig(num_recent_events=3))

    got = run(scenario())
    assert [e.content.parts[0].text for e in got.events] == ["m7", "m8", "m9"]


def test_an_unreadable_event_loses_a_turn_not_the_session():
    """A schema change or a bad write must not make the whole conversation
    unopenable -- that would strand the user with no way forward but a new session."""
    shared = Store()

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id="u", session_id="s_rot")
        await a.append_event(s, _say("user", "before"))
        shared._put("session_events", f"{APP}|u|s_rot|000001", {
            "session_key": f"{APP}|u|s_rot", "n": 1, "event": {"not": "an event"},
        })
        await a.append_event(s, _say("user", "after"))
        return await _svc(shared).get_session(
            app_name=APP, user_id="u", session_id="s_rot")

    got = run(scenario())
    texts = [e.content.parts[0].text for e in got.events]
    assert "before" in texts
    assert len(texts) >= 1


def test_append_event_never_yields_to_the_event_loop():
    """A guard against re-introducing `asyncio.to_thread` in append_event.

    The obvious optimisation -- the Firestore client is blocking, so hop it onto a
    thread -- broke a live FORGE run in a way no unit test caught: ADK runs agents as
    nested async generators wrapped in Aclosing, and a real suspension point inside
    `append_event` lets the loop interleave teardown with the write. The stream died
    mid-run with GeneratorExit and the agents stopped halfway through building tools.

    So: appending must complete without ever handing control back to the loop. Driving
    the coroutine by hand proves it -- if it suspends, `send(None)` yields a future
    instead of raising StopIteration, and this fails.
    """
    shared = Store()
    svc = _svc(shared)
    session = run(svc.create_session(app_name=APP, user_id="u", session_id="s_sync"))

    coro = svc.append_event(session, _say("user", "no awaiting the store"))
    try:
        suspended_on = coro.send(None)
    except StopIteration:
        suspended_on = None
    finally:
        coro.close()

    assert suspended_on is None, (
        "append_event suspended on "
        f"{suspended_on!r} -- something in it awaits the event loop. That breaks ADK's "
        "generator teardown mid-stream. See the docstring on append_event."
    )
    assert shared.get("sessions", f"{APP}|u|s_sync")["n_events"] == 1


@pytest.mark.parametrize("bad", ["a|b", "plain"])
def test_ids_with_the_separator_do_not_collide(bad: str):
    """User ids come from the browser. A user id containing the separator must not let
    one session read another's events."""
    shared = Store()

    async def scenario():
        a = _svc(shared)
        s = await a.create_session(app_name=APP, user_id=bad, session_id="s")
        await a.append_event(s, _say("user", f"hello from {bad}"))
        return await _svc(shared).get_session(app_name=APP, user_id=bad, session_id="s")

    got = run(scenario())
    assert got is not None
    assert got.events[0].content.parts[0].text == f"hello from {bad}"
