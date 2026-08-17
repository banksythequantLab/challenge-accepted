"""A party you can join and never leave is not a party, it is a trap.

For most of this build the roster was append-only. Anyone holding an invite link could
join; nobody could leave and nobody could be removed. A link forwarded once was
permanent access to somebody's plan, their journal and every tool built for them --
and unlike a missing feature, that one is invisible until somebody abuses it.

These are the rules worth pinning, because each one is a decision that could plausibly
have gone the other way and every one of them is a permission:

  * you can always remove YOURSELF, and afterwards you are locked out for real;
  * a plain member cannot remove another member -- that would be a takeover on a
    party you join by clicking a link;
  * the owner can remove anyone;
  * nobody can remove the owner, including the owner, because the challenge document
    names them and an ownerless challenge is not a state the UI can render.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from challenge_accepted.api import router
from challenge_accepted.authgate import current
from challenge_accepted.services import auth
from challenge_accepted.services.store import store

OWNER, MATE, STRANGER = "uid_owner", "uid_mate", "uid_stranger"


@pytest.fixture()
def app_as(monkeypatch):
    """Build a client that acts as whichever uid you name. Auth is ON for all of these.

    With auth off every ownership check trivially passes -- that is what `CA_AUTH=off`
    means -- so a permission test that forgot to turn it on would pass by being
    switched off, which is the most embarrassing shape a green tick can have.
    """
    monkeypatch.setattr(auth, "AUTH_MODE", "required")

    def build(uid: str) -> TestClient:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[current] = lambda: auth.Caller(
            uid=uid, email=f"{uid}@example.com", name=uid)
        return TestClient(app)

    return build


@pytest.fixture()
def quest() -> str:
    cid = store.create_challenge(
        {"outcome": "ship it", "definition_of_done": "deployed"},
        owner_id=OWNER, group_id="grp_exit_test",
    )
    store.join_group("grp_exit_test", OWNER)
    store.join_group("grp_exit_test", MATE)
    return cid


def test_a_member_can_remove_themselves_and_is_then_locked_out(app_as, quest):
    mate = app_as(MATE)
    assert mate.get(f"/api/challenges/{quest}/dashboard").status_code == 200

    r = mate.delete(f"/api/challenges/{quest}/party/{MATE}")
    assert r.status_code == 200, r.text
    assert MATE not in [p["id"] for p in r.json()["party"]]

    # The part that actually matters. Falling off a roster while keeping read access
    # would be a cosmetic exit -- the whole point is that the plan goes away.
    assert mate.get(f"/api/challenges/{quest}/dashboard").status_code == 403
    assert mate.get(f"/api/challenges/{quest}/journal").status_code == 403
    assert quest not in [c["id"] for c in mate.get("/api/challenges").json()["challenges"]]


def test_a_member_cannot_remove_another_member(app_as, quest):
    store.join_group("grp_exit_test", STRANGER)
    r = app_as(MATE).delete(f"/api/challenges/{quest}/party/{STRANGER}")
    assert r.status_code == 403
    assert STRANGER in store.get("groups", "grp_exit_test")["members"]


def test_the_owner_can_remove_someone(app_as, quest):
    r = app_as(OWNER).delete(f"/api/challenges/{quest}/party/{MATE}")
    assert r.status_code == 200, r.text
    assert MATE not in store.get("groups", "grp_exit_test")["members"]


def test_the_owner_cannot_be_removed_by_anyone_including_themselves(app_as, quest):
    assert app_as(MATE).delete(f"/api/challenges/{quest}/party/{OWNER}").status_code == 403
    assert app_as(OWNER).delete(f"/api/challenges/{quest}/party/{OWNER}").status_code == 409
    assert OWNER in store.get("groups", "grp_exit_test")["members"]


def test_leaving_does_not_delete_what_they_discovered(app_as, quest):
    store.add_group_fact("grp_exit_test", "The vendor never answers email on Fridays.")
    app_as(MATE).delete(f"/api/challenges/{quest}/party/{MATE}")
    facts = store.get("groups", "grp_exit_test")["shared_facts"]
    assert any("Fridays" in f for f in facts), (
        "a teammate leaving does not make what they found out untrue, and deleting it "
        "would silently rewrite the plan for everyone still here")


def test_removing_somebody_twice_is_not_an_error(app_as, quest):
    owner = app_as(OWNER)
    assert owner.delete(f"/api/challenges/{quest}/party/{MATE}").status_code == 200
    again = owner.delete(f"/api/challenges/{quest}/party/{MATE}")
    assert again.status_code == 200
    assert again.json()["status"] == "not_a_member"
