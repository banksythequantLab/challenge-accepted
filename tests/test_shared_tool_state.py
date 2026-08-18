"""One party, one copy -- and a save that refuses to overwrite a teammate's.

Personal tool state (tests/test_tool_state.py) is the right default and stays the
default: a training log holds YOUR mileage, and a shared copy would mean a teammate
unticking your boxes without knowing they had. But the whole premise of a party is
coordination, and some tools ARE the coordination: a cost split, a who-is-bringing-what
list, a rota. Those need one record.

What this file pins:

  * scope is decided at BUILD time from the Quartermaster's spec, never by the caller.
    If the client picked, two teammates could open the same tool against different
    keys and each would see a consistent, empty, private copy of a shared list -- a
    failure indistinguishable from "nobody has filled it in yet";
  * a shared tool really is one document: what Dana writes, Derek reads;
  * a personal tool really is not, on the same challenge, at the same time;
  * a save carrying a stale version is REFUSED with 409 and the winning state
    attached, so the client can say who changed it rather than "something happened";
  * a personal tool never conflicts with itself -- two of your own tabs are not a
    race worth failing.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from challenge_accepted.api import router
from challenge_accepted.authgate import current
from challenge_accepted.services import auth
from challenge_accepted.services.store import store

DEREK, DANA = "uid_derek_sh", "uid_dana_sh"


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
def party() -> tuple[str, str, str]:
    """One challenge, two members, and two tools: one shared, one personal."""
    cid = store.create_challenge({"outcome": "ship a hackathon entry"},
                                 owner_id=DEREK, group_id="grp_shared_state")
    store.join_group("grp_shared_state", DEREK)
    store.join_group("grp_shared_state", DANA)
    store.put_node(cid, {"id": "split", "title": "Split the costs",
                         "acceptance_criteria": "x", "depends_on": []})
    shared = store.put_tool(cid, "split", {
        "type": "mini_app", "name": "Cost Split", "source": "<html></html>",
        "usage": "u", "smoke_test_passed": True, "degraded": False, "shared": True})
    personal = store.put_tool(cid, "split", {
        "type": "tracker", "name": "My Hours", "source": "<html></html>",
        "usage": "u", "smoke_test_passed": True, "degraded": False, "shared": False})
    return cid, shared, personal


def test_a_shared_tool_is_one_record_for_the_party(app_as, party):
    """Dana writes, Derek reads. This is the feature."""
    cid, shared, _ = party
    app_as(DANA).put(f"/api/challenges/{cid}/tools/{shared}/state",
                     json={"state": {"dana": "40"}})

    seen = app_as(DEREK).get(f"/api/challenges/{cid}/tools/{shared}/state").json()
    assert seen["state"] == {"dana": "40"}
    assert seen["shared"] is True


def test_a_personal_tool_stays_personal_on_the_same_challenge(app_as, party):
    """The default has not moved. Same party, same moment, separate copies."""
    cid, _, personal = party
    app_as(DANA).put(f"/api/challenges/{cid}/tools/{personal}/state",
                     json={"state": {"hours": "12"}})

    seen = app_as(DEREK).get(f"/api/challenges/{cid}/tools/{personal}/state").json()
    assert seen["state"] == {}, "a personal tool leaked across the party"
    assert seen["shared"] is False


def test_scope_comes_from_the_tool_not_the_caller(app_as, party):
    """A client cannot ask for the other scope, by any parameter it can reach.

    If it could, the failure would be silent and would look like an empty list.
    """
    cid, shared, _ = party
    app_as(DANA).put(f"/api/challenges/{cid}/tools/{shared}/state",
                     json={"state": {"dana": "40"}})

    r = app_as(DEREK).get(
        f"/api/challenges/{cid}/tools/{shared}/state?shared=false&scope=user")
    assert r.json()["state"] == {"dana": "40"}


def test_the_reader_is_told_who_last_saved_it(app_as, party):
    """"Shared" alone tells you the rules. "Last saved by Dana" tells you whether the
    thing in front of you is news."""
    cid, shared, _ = party
    store.put_user(DANA, {"name": "Dana"})
    app_as(DANA).put(f"/api/challenges/{cid}/tools/{shared}/state",
                     json={"state": {"dana": "40"}})

    seen = app_as(DEREK).get(f"/api/challenges/{cid}/tools/{shared}/state").json()
    assert seen["updated_by"] == "Dana"
    assert seen["version"] == 1


def test_a_stale_save_is_refused_with_the_winning_state(app_as, party):
    """The failure this whole mechanism exists to prevent, driven end to end."""
    cid, shared, _ = party
    store.put_user(DANA, {"name": "Dana"})
    derek, dana = app_as(DEREK), app_as(DANA)

    # Both open it. Both hold version 0.
    assert derek.get(f"/api/challenges/{cid}/tools/{shared}/state").json()["version"] == 0
    assert dana.get(f"/api/challenges/{cid}/tools/{shared}/state").json()["version"] == 0

    ok = dana.put(f"/api/challenges/{cid}/tools/{shared}/state",
                  json={"state": {"total": "120"}, "version": 0})
    assert ok.status_code == 200 and ok.json()["version"] == 1

    late = derek.put(f"/api/challenges/{cid}/tools/{shared}/state",
                     json={"state": {"total": "0"}, "version": 0})
    assert late.status_code == 409
    detail = late.json()["detail"]
    assert detail["state"] == {"total": "120"}, "the client cannot recover without it"
    assert detail["updated_by"] == "Dana"
    assert detail["version"] == 1

    # And Dana's number survived. A refused write must change nothing.
    assert derek.get(
        f"/api/challenges/{cid}/tools/{shared}/state").json()["state"] == {"total": "120"}


def test_a_save_with_the_current_version_goes_through(app_as, party):
    """Derek reloads after the conflict, redoes his edit, and it lands."""
    cid, shared, _ = party
    derek, dana = app_as(DEREK), app_as(DANA)
    dana.put(f"/api/challenges/{cid}/tools/{shared}/state",
             json={"state": {"total": "120"}, "version": 0})

    now = derek.get(f"/api/challenges/{cid}/tools/{shared}/state").json()
    r = derek.put(f"/api/challenges/{cid}/tools/{shared}/state",
                  json={"state": {"total": "150"}, "version": now["version"]})
    assert r.status_code == 200 and r.json()["version"] == 2


def test_a_personal_tool_does_not_conflict_with_itself(app_as, party):
    """Two of your own tabs are not a race worth failing, so the client sends no
    version for a personal tool and the server must not invent one."""
    cid, _, personal = party
    me = app_as(DEREK)
    me.put(f"/api/challenges/{cid}/tools/{personal}/state", json={"state": {"a": "1"}})
    r = me.put(f"/api/challenges/{cid}/tools/{personal}/state", json={"state": {"a": "2"}})
    assert r.status_code == 200
    assert me.get(f"/api/challenges/{cid}/tools/{personal}/state").json()["state"] == {"a": "2"}


def test_a_non_member_still_cannot_read_a_shared_tool(app_as, party):
    """Shared means shared with the PARTY. Membership gates it exactly as before."""
    cid, shared, _ = party
    r = app_as("uid_stranger").get(f"/api/challenges/{cid}/tools/{shared}/state")
    assert r.status_code == 403
