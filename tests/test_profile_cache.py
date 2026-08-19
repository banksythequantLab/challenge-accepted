"""The dashboard poll should not re-read a name that cannot have changed.

`/dashboard` is polled every 4s idle and every 1.2s during a run, by every open
browser, for the whole judging window. `check_poll_cost` measured 120 Firestore
reads/minute for ONE idle browser against its 120 budget -- no headroom -- and at that
rate a single page left open exhausts the 50k/day free read quota in about seven hours.

Two of those reads per poll were waste:

  * `/dashboard` read the group doc for `shared_facts`, then `_party` read the SAME
    doc again through `_members`;
  * every party member's `users` doc was re-read on every poll, purely to turn a uid
    into a name and an avatar -- a per-poll cost that grows with the party.

What must NOT regress while fixing that is the roster itself. "A teammate joins and
the header goes 1 -> 2 while you sit still" is the collaborative demo, and a cache
that held the roster for a minute would break exactly that. So membership is read
fresh every poll and only the *profiles* are cached -- and only once they have a name,
because `join` adds the member and writes the profile as two separate writes and a
poll landing between them would otherwise pin `u_9a3d0a` on screen for a full TTL.

Every test here gets its own group and its own uids. The `store` singleton lives for
the whole pytest session, so shared ids would let one test's profile satisfy the next
test's precondition -- and a test that passes because a previous test wrote the row it
was supposed to find missing is exactly the kind of green tick this repo distrusts.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import challenge_accepted.api as capi
from challenge_accepted.api import router
from challenge_accepted.authgate import current
from challenge_accepted.services import auth
from challenge_accepted.services.store import store

_seq = itertools.count()


@dataclass
class Party:
    cid: str
    group: str
    owner: str
    mate: str


@pytest.fixture(autouse=True)
def _clean_cache():
    """Every test starts cold. A cache that leaks across tests proves nothing."""
    capi._profiles.clear()
    yield
    capi._profiles.clear()


@pytest.fixture()
def party() -> Party:
    n = next(_seq)
    p = Party(cid="", group=f"grp_pc_{n}",
              owner=f"uid_pc_owner_{n}", mate=f"uid_pc_mate_{n}")
    p.cid = store.create_challenge(
        {"outcome": "ship it", "definition_of_done": "deployed"},
        owner_id=p.owner, group_id=p.group,
    )
    store.join_group(p.group, p.owner)
    store.put_user(p.owner, {"name": "Derek", "picture": "http://x/d.png"})
    return p


@pytest.fixture()
def client(monkeypatch, party) -> TestClient:
    monkeypatch.setattr(auth, "AUTH_MODE", "required")
    app = FastAPI()
    app.include_router(router)
    # The OWNER, deliberately: `_mine` short-circuits on ownership before it reads the
    # group, so the group reads this test counts are the endpoint's own.
    app.dependency_overrides[current] = lambda: auth.Caller(
        uid=party.owner, email="o@example.com", name="Owner")
    return TestClient(app)


@pytest.fixture()
def reads(monkeypatch) -> Counter:
    """Count Firestore document reads the way Firestore bills them: one per get."""
    counter: Counter = Counter()
    real_get = store.get

    def counted(collection, doc_id):
        counter[collection] += 1
        return real_get(collection, doc_id)

    monkeypatch.setattr(store, "get", counted)
    return counter


def _party_of(client, party) -> list[dict]:
    r = client.get(f"/api/challenges/{party.cid}/dashboard")
    assert r.status_code == 200, r.text
    return r.json()["summary"]["party"]


def test_a_named_profile_is_read_once_across_many_polls(client, party, reads):
    for _ in range(5):
        _party_of(client, party)

    assert reads["users"] == 1, (
        f"5 polls did {reads['users']} user reads; a name that cannot change should "
        "be read once")


def test_the_group_doc_is_read_once_per_poll_not_twice(client, party, reads):
    _party_of(client, party)

    # Shared facts and the roster come from the same document. Reading it twice was
    # the other half of the 120/minute.
    assert reads["groups"] == 1, f"{reads['groups']} group reads in one poll"


def test_the_name_still_reaches_the_screen(client, party):
    first = _party_of(client, party)
    assert first == [{"id": party.owner, "name": "Derek", "picture": "http://x/d.png"}]

    # ...and again from the cache, byte for byte. A cache that serves a DIFFERENT
    # shape on the second call is worse than no cache.
    assert _party_of(client, party) == first


def test_a_teammate_joining_shows_up_on_the_very_next_poll(client, party):
    assert [p["id"] for p in _party_of(client, party)] == [party.owner]

    store.join_group(party.group, party.mate)
    store.put_user(party.mate, {"name": "Dana", "picture": ""})

    after = _party_of(client, party)
    assert [p["id"] for p in after] == [party.owner, party.mate]
    assert [p["name"] for p in after] == ["Derek", "Dana"]


def test_a_profile_written_after_the_join_is_not_stuck_as_a_uid(client, party):
    """The two-write race, run in the order that breaks a naive cache.

    `join` adds the member first and writes the profile second. A poll in between
    reads nothing for that uid -- and if that miss were cached, the teammate would sit
    on screen as a truncated id until the TTL expired, which is the bug `_party`
    exists to prevent.
    """
    store.join_group(party.group, party.mate)

    mid = _party_of(client, party)
    assert [p["name"] for p in mid] == ["Derek", party.mate[:8]]

    store.put_user(party.mate, {"name": "Dana", "picture": ""})

    assert [p["name"] for p in _party_of(client, party)] == ["Derek", "Dana"]


def test_the_cache_expires(client, party, monkeypatch, reads):
    _party_of(client, party)
    assert reads["users"] == 1

    now = capi.time.time()
    monkeypatch.setattr(capi.time, "time", lambda: now + capi.PROFILE_TTL + 1)

    _party_of(client, party)
    assert reads["users"] == 2, "a stale entry should be re-read, not served forever"


def test_a_renamed_user_is_picked_up_after_the_ttl(client, party, monkeypatch):
    assert _party_of(client, party)[0]["name"] == "Derek"

    store.put_user(party.owner, {"name": "Derek S", "picture": ""})
    now = capi.time.time()
    monkeypatch.setattr(capi.time, "time", lambda: now + capi.PROFILE_TTL + 1)

    assert _party_of(client, party)[0]["name"] == "Derek S"
