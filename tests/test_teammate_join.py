"""A teammate who opens /app?id=<cid> must land in the challenge's party.

This is the beat the whole Collaborative Partner claim rests on, and until now it had
only ever been proven by a script that handed both users the same group_id up front.
The real app does not do that. The browser mints `grp_<user_id>` into localStorage the
first time you visit, and sends it as session state on every turn -- so the second user
arrives insisting they are a party of one.

If the server believed them:
  * `read_challenge_state` would return an empty `group_facts`, so the agents would
    re-ask questions the party already answered;
  * `add_group_fact` would file that teammate's discoveries under a group nobody else
    reads, so the Party Knowledge panel would stay empty on both screens.

The fix is that the challenge document owns the group, and session state does not get
a vote whenever a challenge is in scope. These tests pin that.
"""

from __future__ import annotations

from challenge_accepted.agent import warden_instruction
from challenge_accepted.services import tools
from challenge_accepted.services.store import store


class FakeToolContext:
    """Just the surface tools.py touches: a mutable `state` dict."""

    def __init__(self, **state):
        self.state = dict(state)


def _challenge_owned_by_alice() -> str:
    return store.create_challenge(
        {"title": "Ship the demo", "outcome": "a recorded demo video"},
        owner_id="u_alice",
        group_id="grp_u_alice",
    )


def test_teammate_group_id_is_overruled_by_the_challenge():
    cid = _challenge_owned_by_alice()
    # Bob's browser minted this from his own localStorage. It is wrong, and it is
    # exactly what the real client sends.
    bob = FakeToolContext(user_id="u_bob", group_id="grp_u_bob", challenge_id=cid)

    assert tools._group_id(bob) == "grp_u_alice"


def test_the_overrule_is_written_back_into_session_state():
    """Anything reading state directly must agree with _group_id, not fight it."""
    cid = _challenge_owned_by_alice()
    bob = FakeToolContext(user_id="u_bob", group_id="grp_u_bob", challenge_id=cid)

    tools._group_id(bob)
    assert bob.state["group_id"] == "grp_u_alice"


def test_a_teammates_discovery_reaches_the_owner():
    """The actual promise: Bob learns something, Alice sees it."""
    cid = _challenge_owned_by_alice()
    bob = FakeToolContext(user_id="u_bob", group_id="grp_u_bob", challenge_id=cid)

    tools.remember_group_fact(
        "The venue will not confirm a date until the deposit clears.", bob
    )

    alice_sees = (store.get("groups", "grp_u_alice") or {}).get("shared_facts", [])
    assert alice_sees == ["The venue will not confirm a date until the deposit clears."]
    # And nothing was stranded in Bob's private group.
    assert (store.get("groups", "grp_u_bob") or {}).get("shared_facts", []) == []


def test_a_teammate_reads_the_facts_the_owner_already_saved():
    """The other direction: Bob must not be told the party knows nothing."""
    cid = _challenge_owned_by_alice()
    store.add_group_fact("grp_u_alice", "Nobody on the team has admin on GCP billing.")
    bob = FakeToolContext(user_id="u_bob", group_id="grp_u_bob", challenge_id=cid)

    state = tools.read_challenge_state(bob)

    assert "Nobody on the team has admin on GCP billing." in state["group_facts"]


def test_opening_a_challenge_puts_you_on_the_roster():
    cid = _challenge_owned_by_alice()
    bob = FakeToolContext(user_id="u_bob", group_id="grp_u_bob", challenge_id=cid)

    tools._group_id(bob)

    assert store.get("groups", "grp_u_alice")["members"] == ["u_bob"]


def test_the_roster_write_happens_once_per_session():
    """_group_id runs on every tool call; the roster write is a Firestore round trip."""
    cid = _challenge_owned_by_alice()
    bob = FakeToolContext(user_id="u_bob", group_id="grp_u_bob", challenge_id=cid)

    calls: list[tuple[str, str]] = []
    real = store.join_group
    store.join_group = lambda g, u: (calls.append((g, u)), real(g, u))[1]  # type: ignore[method-assign]
    try:
        for _ in range(5):
            tools._group_id(bob)
    finally:
        store.join_group = real  # type: ignore[method-assign]

    assert calls == [("grp_u_alice", "u_bob")]


def test_the_roster_is_idempotent_and_ordered_by_arrival():
    store.join_group("grp_roster", "u_alice")
    store.join_group("grp_roster", "u_bob")
    store.join_group("grp_roster", "u_alice")

    assert store.get("groups", "grp_roster")["members"] == ["u_alice", "u_bob"]


def test_state_still_decides_before_a_charter_exists():
    """During the interview there is no challenge yet, so state is all we have."""
    fresh = FakeToolContext(user_id="u_carol", group_id="grp_u_carol")
    assert tools._group_id(fresh) == "grp_u_carol"


def test_an_unknown_challenge_id_does_not_strand_the_user():
    """A stale bookmark must degrade to the user's own group, not crash a run."""
    stale = FakeToolContext(
        user_id="u_dave", group_id="grp_u_dave", challenge_id="chal_deleted"
    )
    assert tools._group_id(stale) == "grp_u_dave"


def _planned_challenge() -> str:
    """A challenge past ACCEPT and MAP -- charter saved, graph drawn."""
    cid = _challenge_owned_by_alice()
    for nid in ("book-venue", "send-invites", "order-cake"):
        store.put_node(cid, {"id": nid, "title": nid, "acceptance_criteria": "c"})
    store.set_node_status(cid, "book-venue", "done", "confirmation email")
    return cid


def test_warden_is_told_the_challenge_is_in_flight():
    """Rule 8 alone did not hold live. State-derived facts are appended instead."""
    cid = _planned_challenge()
    text = warden_instruction(FakeToolContext(user_id="u_bob", challenge_id=cid))

    assert "A CHALLENGE IS ALREADY IN FLIGHT" in text
    assert "Ship the demo" in text
    assert "1 of 3 steps cleared" in text
    assert "Do NOT transfer to `interviewer`" in text


def test_warden_gets_the_plain_prompt_before_a_charter_exists():
    fresh = warden_instruction(FakeToolContext(user_id="u_bob"))
    assert "A CHALLENGE IS ALREADY IN FLIGHT" not in fresh


def test_warden_gets_the_plain_prompt_between_charter_and_graph():
    """Mid-MAP the normal phase rules are exactly right -- do not suppress MAP."""
    cid = _challenge_owned_by_alice()  # charter, but no nodes yet
    text = warden_instruction(FakeToolContext(user_id="u_bob", challenge_id=cid))
    assert "A CHALLENGE IS ALREADY IN FLIGHT" not in text


def test_a_stale_challenge_id_does_not_break_the_instruction():
    text = warden_instruction(
        FakeToolContext(user_id="u_bob", challenge_id="chal_deleted"))
    assert "A CHALLENGE IS ALREADY IN FLIGHT" not in text
    assert "You are Warden" in text


def test_the_founder_is_on_their_own_roster():
    """Otherwise a solo challenge reports a party of zero."""
    alice = FakeToolContext(user_id="u_erin", group_id="grp_u_erin")
    result = tools.save_charter(
        title="Learn to weld",
        outcome="weld a bike frame that holds",
        definition_of_done="frame survives a 20 mile ride",
        deadline="2026-10-01",
        constraints=["evenings only"],
        prior_attempts=[],
        stakeholders=[],
        tool_context=alice,
    )

    assert result["status"] == "ok"
    assert store.get("groups", "grp_u_erin")["members"] == ["u_erin"]
