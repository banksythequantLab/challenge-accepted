"""A tracker that forgets is a form.

Tools run in a sandboxed iframe with no same-origin privilege, which means no storage,
no cookies and no way to attach a token. So a tool built to log a training week lost
it the moment the modal closed -- and the tool could not even ask for help, because it
has no credential to ask with. The dashboard brokers it: fetch state, hand it in as a
seed, take writes back over postMessage, save them here.

What that design puts on this endpoint, and what these pin:

  * state is per (tool, person). A teammate must not see your mileage, and must not be
    able to untick your boxes;
  * membership still gates it, exactly like every other read of a challenge;
  * a tool that does not belong to this challenge is a 404, not an accidental
    key-value store keyed on anything a client cares to send;
  * there is a size cap, because this is a write endpoint reached by model-written
    JavaScript running in a loop nobody reviewed.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from challenge_accepted.api import TOOL_STATE_LIMIT, router
from challenge_accepted.authgate import current
from challenge_accepted.services import auth
from challenge_accepted.services.store import store

MINE, THEIRS = "uid_mine", "uid_theirs"


@pytest.fixture()
def app_as(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "required")

    def build(uid: str) -> TestClient:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[current] = lambda: auth.Caller(
            uid=uid, email=f"{uid}@example.com", name=uid)
        return TestClient(app)

    return build


@pytest.fixture()
def tool() -> tuple[str, str]:
    cid = store.create_challenge({"outcome": "run a 10k"}, owner_id=MINE,
                                 group_id="grp_tool_state")
    store.join_group("grp_tool_state", MINE)
    store.join_group("grp_tool_state", THEIRS)
    store.put_node(cid, {"id": "base", "title": "Base", "acceptance_criteria": "x",
                         "depends_on": []})
    tid = store.put_tool(cid, "base", {"type": "tracker", "name": "Weekly Log",
                                       "source": "<html></html>", "usage": "u",
                                       "smoke_test_passed": True, "degraded": False})
    return cid, tid


def test_it_starts_empty_and_remembers_what_you_put_in_it(app_as, tool):
    cid, tid = tool
    me = app_as(MINE)
    assert me.get(f"/api/challenges/{cid}/tools/{tid}/state").json()["state"] == {}

    entries = {"entries": '[{"km": 8.2, "when": "Tue"}]'}
    assert me.put(f"/api/challenges/{cid}/tools/{tid}/state",
                  json={"state": entries}).status_code == 200
    assert me.get(f"/api/challenges/{cid}/tools/{tid}/state").json()["state"] == entries


def test_a_teammate_has_their_own_and_cannot_see_yours(app_as, tool):
    """Both are on the party. Neither is on the other's training log.

    Sharing this would be a shared-editing model nobody asked for, and the first
    surprise would be a teammate silently unticking your boxes.
    """
    cid, tid = tool
    app_as(MINE).put(f"/api/challenges/{cid}/tools/{tid}/state",
                     json={"state": {"entries": "mine"}})
    theirs = app_as(THEIRS).get(f"/api/challenges/{cid}/tools/{tid}/state")
    assert theirs.status_code == 200
    assert theirs.json()["state"] == {}, "a teammate was handed someone else's log"


def test_a_stranger_gets_nothing(app_as, tool):
    cid, tid = tool
    stranger = app_as("uid_nobody")
    assert stranger.get(f"/api/challenges/{cid}/tools/{tid}/state").status_code == 403
    assert stranger.put(f"/api/challenges/{cid}/tools/{tid}/state",
                        json={"state": {"a": "b"}}).status_code == 403


def test_you_cannot_invent_a_tool_to_write_under(app_as, tool):
    """Otherwise this is a free key-value store keyed on anything the client sends."""
    cid, _ = tool
    r = app_as(MINE).put(f"/api/challenges/{cid}/tools/tool_not_real/state",
                         json={"state": {"a": "b"}})
    assert r.status_code == 404


def test_oversized_state_is_refused_rather_than_truncated(app_as, tool):
    """Silently keeping half of somebody's log is worse than refusing all of it.

    The tool is told, the dashboard surfaces it, and the user finds out now instead of
    discovering months later that the tail of their season is missing.
    """
    cid, tid = tool
    big = {"blob": "x" * (TOOL_STATE_LIMIT + 1000)}
    r = app_as(MINE).put(f"/api/challenges/{cid}/tools/{tid}/state", json={"state": big})
    assert r.status_code == 413
    assert str(TOOL_STATE_LIMIT) in r.json()["detail"]
    saved = store.get_tool_state(tid, MINE)
    assert saved["data"] == {}, "the oversized write partially landed"
    assert saved["version"] == 0, "a refused write must not burn a version"


def test_saving_twice_replaces_rather_than_merges(app_as, tool):
    """The tool owns the shape. The browser posts its whole bag every time, so a key
    the tool deleted must actually disappear -- merging here would resurrect it."""
    cid, tid = tool
    me = app_as(MINE)
    me.put(f"/api/challenges/{cid}/tools/{tid}/state", json={"state": {"a": "1", "b": "2"}})
    me.put(f"/api/challenges/{cid}/tools/{tid}/state", json={"state": {"a": "9"}})
    assert me.get(f"/api/challenges/{cid}/tools/{tid}/state").json()["state"] == {"a": "9"}
