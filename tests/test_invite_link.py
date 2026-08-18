"""An invite link you cannot take back is not an invitation, it is a key under a mat.

The link used to be the challenge id alone. Forward it once, or leave it in a
screenshot, and that was access to somebody's plan for good -- the only remedy being
eviction, which requires first noticing. The membership wall was built to stop a leaked
id being access; a permanent link put the hole straight back.

An approval step was the other candidate and it loses on both counts. It puts a person
in the loop on the beat that has to be instant -- a teammate opening a link and being
met by what the party already knows -- and it still cannot un-send a link that has
already gone. A rotatable secret can.

The rules that fall out of that, and why each could have gone the other way:

  * joining needs the key. Otherwise nothing changed;
  * MEMBERS do not need it. Rotation happens because a link leaked, and locking out the
    people it was rotated to protect would make the button useless exactly when it
    matters;
  * any member can read the key -- pulling in a third person is how a party grows, and
    routing that through the founder would be a workflow rule wearing a security badge;
  * only the OWNER can rotate it, because rotating takes a capability away from
    everyone they have already handed it to.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from challenge_accepted.api import router
from challenge_accepted.authgate import current
from challenge_accepted.services import auth
from challenge_accepted.services.store import store

OWNER, MATE, OUTSIDER = "uid_owner_i", "uid_mate_i", "uid_outsider_i"


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
def quest() -> str:
    cid = store.create_challenge({"outcome": "ship it"}, owner_id=OWNER,
                                 group_id="grp_invite_test")
    store.join_group("grp_invite_test", OWNER)
    return cid


def _key(app_as, cid: str, uid: str = OWNER) -> str:
    return app_as(uid).get(f"/api/challenges/{cid}/invite").json()["token"]


def test_the_id_alone_is_no_longer_enough(app_as, quest):
    outsider = app_as(OUTSIDER)
    assert outsider.post(f"/api/challenges/{quest}/join",
                         json={"user_id": OUTSIDER}).status_code == 403
    assert outsider.post(f"/api/challenges/{quest}/join",
                         json={"user_id": OUTSIDER, "token": "guessed"}).status_code == 403
    assert OUTSIDER not in store.get("groups", "grp_invite_test")["members"]


def test_the_key_lets_you_in(app_as, quest):
    r = app_as(MATE).post(f"/api/challenges/{quest}/join",
                          json={"user_id": MATE, "token": _key(app_as, quest)})
    assert r.status_code == 200, r.text
    assert MATE in [p["id"] for p in r.json()["party"]]


def test_the_key_is_a_secret_from_people_who_are_not_on_the_party(app_as, quest):
    assert app_as(OUTSIDER).get(f"/api/challenges/{quest}/invite").status_code == 403


def test_any_member_can_pass_the_link_on(app_as, quest):
    """Not owner-only. A teammate pulling in a third person is how a party grows."""
    app_as(MATE).post(f"/api/challenges/{quest}/join",
                      json={"user_id": MATE, "token": _key(app_as, quest)})
    assert app_as(MATE).get(f"/api/challenges/{quest}/invite").status_code == 200


def test_rotating_kills_every_link_already_sent(app_as, quest):
    old = _key(app_as, quest)
    rotated = app_as(OWNER).post(f"/api/challenges/{quest}/invite/rotate")
    assert rotated.status_code == 200
    new = rotated.json()["token"]
    assert new and new != old

    assert app_as(OUTSIDER).post(f"/api/challenges/{quest}/join",
                                 json={"user_id": OUTSIDER, "token": old}).status_code == 403
    assert app_as(OUTSIDER).post(f"/api/challenges/{quest}/join",
                                 json={"user_id": OUTSIDER, "token": new}).status_code == 200


def test_rotating_does_not_evict_the_people_it_protects(app_as, quest):
    """The whole reason you rotate is that a link got out. If that also threw out the
    teammates already working, nobody would ever press it."""
    app_as(MATE).post(f"/api/challenges/{quest}/join",
                      json={"user_id": MATE, "token": _key(app_as, quest)})
    app_as(OWNER).post(f"/api/challenges/{quest}/invite/rotate")

    mate = app_as(MATE)
    assert mate.get(f"/api/challenges/{quest}/dashboard").status_code == 200
    # And re-announcing themselves must not need the new key they were never sent.
    assert mate.post(f"/api/challenges/{quest}/join",
                     json={"user_id": MATE}).status_code == 200


def test_only_the_owner_can_rotate(app_as, quest):
    app_as(MATE).post(f"/api/challenges/{quest}/join",
                      json={"user_id": MATE, "token": _key(app_as, quest)})
    before = _key(app_as, quest)
    assert app_as(MATE).post(f"/api/challenges/{quest}/invite/rotate").status_code == 403
    assert _key(app_as, quest) == before, "a member rotated the owner's link anyway"


def test_the_owner_never_needs_a_key_for_their_own_quest(app_as, quest):
    assert app_as(OWNER).post(f"/api/challenges/{quest}/join",
                              json={"user_id": OWNER}).status_code == 200


def test_the_key_is_stable_until_somebody_rotates_it(app_as, quest):
    """Minted lazily, so this is the assertion that it is minted ONCE. A token that
    regenerated per request would fail every link the moment it was sent."""
    assert _key(app_as, quest) == _key(app_as, quest)
